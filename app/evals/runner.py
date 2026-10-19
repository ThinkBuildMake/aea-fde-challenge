"""runEval: plays every scenario on a worker's private app instance and writes the run record."""

import json
import logging
import os
import secrets
import shutil
import sqlite3
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.db import apply_migrations, connect_app_db
from app.evals.caller import CallerModel
from app.evals.checks import (
    db_diff,
    forbidden_hits,
    invariant_violations,
    seeded_customer_strings,
    unsupported_figures,
)
from app.evals.records import (
    Judge,
    RunEnvironment,
    RunResult,
    Scenario,
    ScenarioResult,
    TranscriptLine,
)
from app.evals.summary import SEEDED_CUSTOMERS, compute_summary
from app.knowledge.embeddings import Embedder
from app.llm import ModelProvider
from app.main import create_app
from app.settings import Settings
from app.startup import MIGRATIONS_DIR

log = logging.getLogger("meridian.evals")

NO_LIMIT = 10**9
Reporter = Callable[[RunResult, list[Scenario]], None]


@dataclass
class Grade:
    facts_missing: list[str] = field(default_factory=list)
    judge: Judge = field(default_factory=Judge)


def grade_answer(scenario: Scenario, transcript: Sequence[TranscriptLine]) -> Grade:
    """Stub until the judge lands (S28/S41): no missing facts, not graded."""
    return Grade()


def make_run_id() -> str:
    return f"run-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"


def _replace_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".tmp")
    shutil.copyfile(source, temp)
    os.replace(temp, target)


class Worker:
    """One private app instance: its own scheduling copy and app database."""

    def __init__(
        self,
        number: int,
        settings: Settings,
        folder: Path,
        embedder: Embedder | None,
    ) -> None:
        self.number = number
        self.seed = settings.SEED_DB_PATH
        self.settings = settings.model_copy(
            update={
                "SCHEDULING_DB_PATH": folder / "scheduling.sqlite",
                "APP_DB_PATH": folder / "app.sqlite",
                "NEW_CONVERSATIONS_PER_HOUR": NO_LIMIT,
                "MESSAGES_PER_MINUTE": NO_LIMIT,
            }
        )
        self.app = create_app(self.settings, embedder=embedder)

    def reseed(self) -> None:
        """A fresh copy of the supplied bookings and an empty app database."""
        _replace_file(self.seed, self.settings.SCHEDULING_DB_PATH)
        app_db = self.settings.APP_DB_PATH
        for suffix in ("", "-wal", "-shm"):
            Path(str(app_db) + suffix).unlink(missing_ok=True)
        with closing(connect_app_db(app_db)) as conn:
            apply_migrations(conn, MIGRATIONS_DIR)


def _post(client: TestClient, path: str, body: dict[str, Any] | None = None) -> Any:
    response = client.post(path, json=body)
    if response.status_code not in (200, 201):
        raise RuntimeError(
            f"POST {path.split('/')[-1]} returned {response.status_code}"
        )
    return response.json()


def _drive(
    client: TestClient, scenario: Scenario, caller: CallerModel, max_turns: int
) -> tuple[str, float]:
    """Play the conversation over the caller's routes; returns its id and the caller's cost."""
    conversation_id = _post(client, "/conversations")["conversationId"]
    messages = f"/conversations/{conversation_id}/messages"
    transcript: list[tuple[str, str]] = []
    cost = 0.0
    text: str | None = scenario.opening
    for _ in range(max_turns):
        if text is None:
            break
        reply = _post(client, messages, {"text": text})
        transcript += [("caller", text), ("agent", reply["text"])]
        if reply["status"] != "active":
            break
        move = caller.next_move(scenario, transcript)
        cost += move.cost_usd
        if move.done:
            if move.solved is not None:
                _post(
                    client,
                    f"/conversations/{conversation_id}/solved",
                    {"answer": "yes" if move.solved else "no"},
                )
            break
        text = move.text
    return conversation_id, cost


def _read_conversation(app_db: Path, conversation_id: str) -> dict[str, Any]:
    with closing(connect_app_db(app_db)) as conn:
        conn.row_factory = sqlite3.Row
        conversation = conn.execute(
            "SELECT outcome, cost_usd FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        turns = conn.execute(
            "SELECT kind, caller_text, reply_text, model_messages, has_write, latency_ms "
            "FROM turns WHERE conversation_id = ? ORDER BY seq",
            (conversation_id,),
        ).fetchall()
        handoff = conn.execute(
            "SELECT reason, intent, told_caller, customer_id, caller_name "
            "FROM handoffs WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        waitlist = conn.execute(
            "SELECT count(*) FROM waitlist_entries WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()[0]
    return {
        "outcome": conversation["outcome"] if conversation else None,
        "cost_usd": conversation["cost_usd"] if conversation else 0.0,
        "turns": [dict(t) for t in turns],
        "handoff": dict(handoff) if handoff else None,
        "waitlist": waitlist,
    }


def _tool_texts(model_messages: str) -> list[str]:
    return [
        str(m.get("content") or "")
        for m in json.loads(model_messages)
        if m.get("role") == "tool"
    ]


def db_change_counts(
    diff: dict[str, Any], handoffs: int, waitlist: int
) -> dict[str, int]:
    """The dbChange numbers (S26's shape) as the run's database difference shows them."""
    appointments = diff.get("appointments", {})
    changed = appointments.get("changed", [])
    slots = diff.get("appointment_slots", {}).get("changed", [])
    return {
        "appointmentsAdded": len(appointments.get("added", [])),
        "appointmentsCancelled": sum(
            1
            for c in changed
            if c["after"]["status"] == "cancelled"
            and c["before"]["status"] != "cancelled"
        ),
        "appointmentsMoved": sum(
            1
            for c in changed
            if c["after"]["slot_id"] != c["before"]["slot_id"]
            and c["after"]["status"] == "scheduled"
        ),
        "slotsBooked": sum(
            1
            for c in slots
            if c["after"]["status"] == "booked" and c["before"]["status"] != "booked"
        ),
        "slotsFreed": sum(
            1
            for c in slots
            if c["before"]["status"] == "booked" and c["after"]["status"] != "booked"
        ),
        "waitlistRows": waitlist,
        "handoffRows": handoffs,
    }


def _mismatches(scenario: Scenario, actual: dict[str, int]) -> list[str]:
    expected = scenario.expected.db_change
    if expected is None:
        return []
    wanted = {
        "appointmentsAdded": expected.appointments_added,
        "appointmentsCancelled": expected.appointments_cancelled,
        "appointmentsMoved": expected.appointments_moved,
        "slotsBooked": expected.slots_booked,
        "slotsFreed": expected.slots_freed,
        "waitlistRows": expected.waitlist_rows,
        "handoffRows": expected.handoff_rows,
    }
    return [
        f"{name}: expected {wanted[name]}, saw {actual[name]}"
        for name in wanted
        if wanted[name] != actual[name]
    ]


def _handoff_complete(handoff: dict[str, Any] | None) -> bool | None:
    if handoff is None:
        return None
    return bool(
        handoff["reason"]
        and handoff["intent"]
        and handoff["told_caller"]
        and (handoff["caller_name"] or handoff["customer_id"])
    )


def _play(
    worker: Worker, scenario: Scenario, model: ModelProvider, caller: CallerModel
) -> ScenarioResult:
    worker.reseed()
    worker.app.state.ctx.model = model
    client = TestClient(worker.app, raise_server_exceptions=False)
    conversation_id, caller_cost = _drive(client, scenario, caller, scenario.max_turns)
    read = _read_conversation(worker.settings.APP_DB_PATH, conversation_id)
    live = worker.settings.SCHEDULING_DB_PATH
    transcript: list[TranscriptLine] = []
    figure_input: list[tuple[str, list[str]]] = []
    latencies: list[int] = []
    for turn in read["turns"]:
        transcript.append(TranscriptLine(role="caller", text=turn["caller_text"]))
        transcript.append(
            TranscriptLine(
                role="agent",
                text=turn["reply_text"],
                latency_ms=turn["latency_ms"],
                has_write=bool(turn["has_write"]),
            )
        )
        if turn["kind"] == "message":
            latencies.append(turn["latency_ms"])
            figure_input.append(
                (turn["reply_text"], _tool_texts(turn["model_messages"]))
            )
    diff = db_diff(worker.seed, live)
    notes = invariant_violations(
        worker.seed, live, worker.settings.APP_DB_PATH, conversation_id
    )
    observed = read["outcome"] or "unfinished"
    figures = unsupported_figures(figure_input)
    hits = forbidden_hits(
        [t.text for t in transcript if t.role == "agent"], scenario.expected.forbidden
    )
    grade = grade_answer(scenario, transcript)
    counts = db_change_counts(diff, int(read["handoff"] is not None), read["waitlist"])
    mismatches = _mismatches(scenario, counts)
    return ScenarioResult(
        scenario_id=scenario.id,
        observed_outcome=observed,
        contained_correct=(
            observed == scenario.expected.outcome
            and not grade.facts_missing
            and not grade.judge.contradictions
            and not hits
            and figures == 0
            and not notes
            and not mismatches
        ),
        facts_missing=grade.facts_missing,
        forbidden_hits=hits,
        unsupported_figures=figures,
        db_diff=diff,
        invariant_violations=len(notes),
        invariant_notes=notes,
        turns=len(latencies),
        latencies_ms=latencies,
        cost_usd=round(float(read["cost_usd"]) + caller_cost, 6),
        judge=grade.judge,
        handoff_record_complete=_handoff_complete(read["handoff"]),
        transcript=transcript,
        db_change_mismatches=mismatches,
        worker=worker.number,
        copy_path=str(live),
    )


def _run_worker(
    worker: Worker,
    batch: list[Scenario],
    agent_model: Callable[[Scenario], ModelProvider],
    caller: CallerModel,
) -> list[ScenarioResult]:
    results: list[ScenarioResult] = []
    for scenario in batch:
        try:
            results.append(_play(worker, scenario, agent_model(scenario), caller))
        except Exception as error:  # noqa: BLE001 - a failing scenario is reported, not skipped
            log.warning("scenario %s failed: %s", scenario.id, type(error).__name__)
            results.append(
                ScenarioResult(
                    scenario_id=scenario.id,
                    observed_outcome="error",
                    worker=worker.number,
                    copy_path=str(worker.settings.SCHEDULING_DB_PATH),
                    error=f"{type(error).__name__}: {error}"[:300],
                )
            )
    return results


def _write(path: Path, run: RunResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(run.model_dump(by_alias=True, mode="json"), indent=2))
    os.replace(temp, path)


def _report(
    reporter: Reporter, run: RunResult, scenarios: list[Scenario], timeout_s: float
) -> None:
    def call() -> None:
        try:
            reporter(run, scenarios)
        except Exception as error:  # noqa: BLE001 - reporting never fails the run
            log.warning("report failed: %s", type(error).__name__)

    thread = threading.Thread(target=call, daemon=True)
    thread.start()
    thread.join(timeout_s)


def run_eval(
    scenarios: Sequence[Scenario],
    weights: dict[str, int],
    *,
    settings: Settings,
    out_path: Path,
    work_dir: Path,
    agent_model: Callable[[Scenario], ModelProvider],
    caller: CallerModel,
    environment: RunEnvironment,
    workers: int = 4,
    embedder: Embedder | None = None,
    reporter: Reporter | None = None,
    reporter_timeout_s: float = 60,
    run_id: str | None = None,
    keep_work_dir: bool = False,
) -> RunResult:
    """Play every scenario, `workers` at a time, each worker on its own copies; write the record.

    The caller's own scheduling file is never opened: workers copy settings.SEED_DB_PATH.
    """
    started_at = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    scenario_list = list(scenarios)
    count = max(1, min(workers, len(scenario_list)))
    batches = [scenario_list[i::count] for i in range(count)]
    pool_workers = [
        Worker(i + 1, settings, work_dir / f"worker-{i + 1}", embedder)
        for i in range(count)
    ]
    try:
        with ThreadPoolExecutor(max_workers=count) as pool:
            futures = [
                pool.submit(_run_worker, w, batch, agent_model, caller)
                for w, batch in zip(pool_workers, batches, strict=True)
            ]
            by_id = {r.scenario_id: r for f in futures for r in f.result()}
    finally:
        if not keep_work_dir:
            shutil.rmtree(work_dir, ignore_errors=True)
    results = [by_id[s.id] for s in scenario_list]
    customers = {
        *SEEDED_CUSTOMERS,
        *(s.customer_id for s in scenario_list if s.customer_id),
    }
    run = RunResult(
        run_id=run_id or make_run_id(),
        started_at=started_at,
        environment=environment,
        scenarios=results,
        summary=compute_summary(
            scenario_list,
            results,
            weights,
            seeded_customer_strings(settings.SEED_DB_PATH, sorted(customers)),
        ),
    )
    _write(out_path, run)
    if reporter is not None:
        _report(reporter, run, scenario_list, reporter_timeout_s)
    return run
