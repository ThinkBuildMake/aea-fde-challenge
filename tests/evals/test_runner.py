import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from app.evals.caller import ScriptedCaller
from app.evals.environment import describe_environment
from app.evals.records import (
    RunEnvironment,
    RunResult,
    Scenario,
    load_scenarios,
)
from app.evals.runner import run_eval
from app.llm import FakeModelProvider, ModelProvider
from app.settings import REPO_ROOT, Settings
from tests.test_turn import assistant, result, tool_call

FIXTURES = Path(__file__).parent / "fixtures" / "scenarios"
WEIGHTS = {"booking": 120, "membership": 38}
YES = "Yes, book it."


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def booking_model() -> FakeModelProvider:
    return FakeModelProvider(
        results=[
            result(
                assistant(
                    calls=[
                        {
                            "id": "i",
                            "type": "function",
                            "function": {
                                "name": "identify_customer",
                                "arguments": json.dumps(
                                    {"name": "Linda Foster", "phone": "512-555-0101"}
                                ),
                            },
                        },
                        tool_call("w", "find_open_windows", serviceType="hvac_repair"),
                    ]
                )
            ),
            result(assistant("Monday morning is open. Shall I book it?")),
            result(
                assistant(
                    calls=[
                        tool_call(
                            "b",
                            "book_visit",
                            slotId=56,
                            issue="AC not cooling",
                            callerQuote=YES,
                        )
                    ]
                )
            ),
            result(assistant("You are booked for Monday morning.")),
        ]
    )


def figure_model() -> FakeModelProvider:
    return FakeModelProvider(results=[result(assistant("The diagnostic is $79."))])


def model_for(scenario: Scenario) -> ModelProvider:
    return booking_model() if scenario.id.startswith("SYN-BOOK") else figure_model()


def eight_scenarios() -> list[Scenario]:
    base = {s.id: s for s in load_scenarios(FIXTURES)}
    out: list[Scenario] = []
    for n in range(4):
        out.append(base["SYN-BOOK"].model_copy(update={"id": f"SYN-BOOK-{n}"}))
        out.append(base["SYN-FIG"].model_copy(update={"id": f"SYN-FIG-{n}"}))
    return out


def caller_for(scenarios: list[Scenario]) -> ScriptedCaller:
    return ScriptedCaller(
        {s.id: [YES] for s in scenarios if s.id.startswith("SYN-BOOK")}
    )


def environment(settings: Settings) -> RunEnvironment:
    return describe_environment(
        settings,
        settings.SEED_DB_PATH,
        settings.INDEX_PATH,
        versions=lambda slugs: {s: f"{s}-20260101" for s in slugs},
    )


@pytest.fixture
def live(tmp_settings: Settings, seed_path: Path) -> Settings:
    tmp_settings.SCHEDULING_DB_PATH.parent.mkdir(parents=True)
    tmp_settings.SCHEDULING_DB_PATH.write_bytes(seed_path.read_bytes())
    return tmp_settings


def play(
    settings: Settings,
    tmp_path: Path,
    scenarios: list[Scenario],
    caller: ScriptedCaller | None = None,
    **extra,
) -> RunResult:
    return run_eval(
        scenarios,
        WEIGHTS,
        settings=settings,
        out_path=tmp_path / "runs" / "run.json",
        work_dir=tmp_path / "work",
        agent_model=model_for,
        caller=caller or caller_for(scenarios),
        environment=environment(settings),
        **extra,
    )


def test_each_scenario_runs_on_a_freshly_seeded_copy(live: Settings, tmp_path: Path):
    scenarios = eight_scenarios()
    live_before, seed_before = sha(live.SCHEDULING_DB_PATH), sha(live.SEED_DB_PATH)
    run = play(live, tmp_path, scenarios, workers=4)
    print([(r.scenario_id, r.worker, r.observed_outcome) for r in run.scenarios])
    assert len(run.scenarios) == 8 and all(r.error is None for r in run.scenarios)
    booked = [r for r in run.scenarios if r.scenario_id.startswith("SYN-BOOK")]
    for r in booked:
        diff = r.db_diff
        assert len(diff["appointments"]["added"]) == 1
        (slot,) = diff["appointment_slots"]["changed"]
        assert slot["key"] == 56 and slot["before"]["status"] == "open"
    assert sha(live.SCHEDULING_DB_PATH) == live_before
    assert sha(live.SEED_DB_PATH) == seed_before
    assert all(
        r.copy_path not in (str(live.SCHEDULING_DB_PATH), str(live.SEED_DB_PATH))
        for r in run.scenarios
    )


def test_a_failing_scenario_is_reported_not_skipped(live: Settings, tmp_path: Path):
    scenarios = eight_scenarios()
    caller = caller_for(scenarios)
    caller.fail_on = {"SYN-BOOK-1"}
    run = play(live, tmp_path, scenarios, caller)
    failed = [r for r in run.scenarios if r.observed_outcome == "error"]
    print(run.summary.errored, run.summary.errored_ids, failed[0].error)
    assert len(run.scenarios) == 8 and len(failed) == 1
    assert failed[0].scenario_id == "SYN-BOOK-1" and failed[0].error
    assert all(
        r.observed_outcome == "contained" for r in run.scenarios if r is not failed[0]
    )
    assert run.summary.errored == 1 and run.summary.errored_ids == ["SYN-BOOK-1"]


def test_run_record_names_its_environment(live: Settings, tmp_path: Path):
    scenarios = eight_scenarios()[:2]
    play(live, tmp_path, scenarios)
    record = json.loads((tmp_path / "runs" / "run.json").read_text())
    env = record["environment"]
    print(env)
    for key in (
        "agentModel",
        "safetyModel",
        "callerModel",
        "judgeModel",
        "embeddingModel",
    ):
        assert env[key] and env["modelVersions"][env[key]].endswith("-20260101")
    assert env["kbIndexVersion"] == "none"
    assert env["dbSnapshotId"] == "sha256:" + sha(live.SEED_DB_PATH)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert env["appCommit"].startswith(head)
    RunResult.model_validate(record)

    for broken in (
        {"kbIndexVersion": ""},
        {"dbSnapshotId": ""},
        {"appCommit": ""},
        {"modelVersions": {}},
    ):
        data = {**env, **broken}
        with pytest.raises(ValueError):
            RunEnvironment.model_validate(data)


def test_booking_scenario_records_its_database_difference(
    live: Settings, tmp_path: Path
):
    run = play(live, tmp_path, [s for s in eight_scenarios() if s.id == "SYN-BOOK-0"])
    (r,) = run.scenarios
    print(r.db_diff["appointments"]["added"], r.db_diff["appointment_slots"]["changed"])
    (added,) = r.db_diff["appointments"]["added"]
    assert (added["slot_id"], added["customer_id"], added["status"]) == (
        56,
        "MHC-10001",
        "scheduled",
    )
    (slot,) = r.db_diff["appointment_slots"]["changed"]
    assert (slot["key"], slot["before"]["status"], slot["after"]["status"]) == (
        56,
        "open",
        "booked",
    )
    assert set(r.db_diff) == {"appointments", "appointment_slots"}
    assert r.invariant_violations == 0
    assert r.db_change_mismatches == []
    assert r.contained_correct and r.observed_outcome == "contained"


def test_db_change_mismatch_is_recorded_not_fatal(live: Settings, tmp_path: Path):
    scenario = next(s for s in eight_scenarios() if s.id == "SYN-BOOK-0")
    assert scenario.expected.db_change is not None
    scenario.expected.db_change.appointments_added = 2
    run = play(live, tmp_path, [scenario])
    (r,) = run.scenarios
    assert r.db_change_mismatches == ["appointmentsAdded: expected 2, saw 1"]
    assert run.summary.db_change_mismatches == 1
    assert r.observed_outcome == "contained"


def test_unsupported_figure_is_counted(live: Settings, tmp_path: Path):
    run = play(live, tmp_path, [s for s in eight_scenarios() if s.id == "SYN-FIG-0"])
    (r,) = run.scenarios
    print(r.unsupported_figures, [t.text for t in r.transcript])
    assert r.unsupported_figures == 1
    assert run.summary.unsupported_figures == 1


def test_four_workers_on_separate_copies_hold_the_invariants(
    live: Settings, tmp_path: Path
):
    run = play(live, tmp_path, eight_scenarios(), workers=4)
    print(sorted({r.worker for r in run.scenarios}), run.summary.invariant_violations)
    assert len({r.worker for r in run.scenarios}) == 4
    assert len({r.copy_path for r in run.scenarios}) == 4
    assert all(r.invariant_violations == 0 for r in run.scenarios)
    assert run.summary.invariant_violations == 0
    assert not (tmp_path / "work").exists()


def test_a_failing_reporter_never_fails_the_run(live: Settings, tmp_path: Path):
    def boom(run: RunResult, scenarios: list[Scenario]) -> None:
        raise RuntimeError("down")

    run = play(live, tmp_path, eight_scenarios()[:2], reporter=boom)
    assert len(run.scenarios) == 2 and (tmp_path / "runs" / "run.json").is_file()
