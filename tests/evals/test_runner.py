import json
import subprocess
from pathlib import Path

import pytest

from app.conversation import guards
from app.evals.records import RunEnvironment, RunResult, Scenario
from app.settings import REPO_ROOT, Settings
from tests.evals.helpers import (
    caller_for,
    eight_scenarios,
    play,
    sha,
    write_small_index,
)
from tests.evals.test_judge import FakeJudgeClient


def test_each_scenario_runs_on_a_freshly_seeded_copy(live: Settings, tmp_path: Path):
    scenarios = eight_scenarios()
    live_before, seed_before = sha(live.SCHEDULING_DB_PATH), sha(live.SEED_DB_PATH)
    run = play(live, tmp_path, scenarios, workers=4)
    print([(r.scenario_id, r.worker, r.observed_outcome) for r in run.scenarios])
    assert len(run.scenarios) == 8 and all(r.error is None for r in run.scenarios)
    booked = [r for r in run.scenarios if r.scenario_id.startswith("SYN-BOOK")]
    for r in booked:
        # A copy that was not reseeded would refuse slot 56 the second time on a worker.
        writes = [line.has_write for line in r.transcript if line.role == "agent"]
        print(r.scenario_id, "worker", r.worker, "agent write turns", sum(writes))
        assert any(writes), r.scenario_id
        assert r.contained_correct, r.scenario_id
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
    version = write_small_index(live.INDEX_PATH)
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
    assert env["kbIndexVersion"] == version
    print("kbIndexVersion in the record:", env["kbIndexVersion"])
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
    assert r.contained_correct is False
    assert run.summary.projected_containment_pct == 0.0


def test_unsupported_figure_is_counted(
    live: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # The app's own reply check (S45) withholds such a figure; turn it off so the
    # eval's independent check is what catches it.
    monkeypatch.setattr(guards, "unsupported_figures", lambda *_a, **_k: [])
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


def test_app_guard_withholds_the_unsupported_figure(live: Settings, tmp_path: Path):
    run = play(live, tmp_path, [s for s in eight_scenarios() if s.id == "SYN-FIG-0"])
    (r,) = run.scenarios
    print(r.unsupported_figures, [t.text for t in r.transcript])
    assert r.unsupported_figures == 0
    assert "did not want to guess" in r.transcript[-1].text


def test_judge_verdict_and_agreement_reach_the_record(live: Settings, tmp_path: Path):
    scenarios = [s for s in eight_scenarios() if s.id in ("SYN-BOOK-0", "SYN-BOOK-1")]
    judge = FakeJudgeClient(
        replies=[
            ('{"facts": [{"index": 1, "present": true}], "contradictions": []}', 0.25),
            RuntimeError("judge down"),
        ]
    )
    grades = {"SYN-BOOK-0": "pass", "SYN-BOOK-1": "pass"}

    play(live, tmp_path, scenarios, workers=1, judge=judge, human_grades=grades)

    record = json.loads((tmp_path / "runs" / "run.json").read_text())
    first, second = record["scenarios"]
    print(
        [
            (r["scenarioId"], r["judge"], r["containedCorrect"], r["costUsd"])
            for r in (first, second)
        ],
        record["summary"]["judgeAgreement"],
    )
    assert first["judge"]["verdict"] == "pass"
    assert first["judge"]["facts"] == [
        {"fact": "a repair visit is booked", "present": True}
    ]
    assert first["containedCorrect"] is True
    # Same conversation cost on both; only the first judge call cost something.
    assert first["costUsd"] == pytest.approx(second["costUsd"] + 0.25)
    assert second["judge"]["verdict"] == "error"
    assert second["judge"]["notes"] == "RuntimeError"
    assert second["containedCorrect"] is False
    assert record["summary"]["judgeAgreement"] == {"agreed": 1, "of": 2}
