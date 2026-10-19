import json
from pathlib import Path
from typing import Any

from app.evals.langfuse_check import check
from tests.evals.runs import sample_run, write_run


def fake_fetch(run_id: str, outcomes: dict[str, str], experiments: int = 1):
    calls: list[tuple[str, dict[str, Any]]] = []

    def fetch(path: str, params: dict[str, Any]) -> dict[str, Any]:
        calls.append((path, params))
        if path == "/api/public/experiments":
            data = [
                {"name": run_id, "itemCount": len(outcomes)} for _ in range(experiments)
            ]
            return {"data": data, "meta": {}}
        assert path == "/api/public/experiment-items"
        return {
            "data": [
                {
                    "experimentName": run_id,
                    "input": json.dumps({"scenarioId": sid}),
                    "output": json.dumps({"observedOutcome": outcome}),
                }
                for sid, outcome in outcomes.items()
            ],
            "meta": {},
        }

    return fetch, calls


def test_matching_items_report_ok(tmp_path: Path):
    run = sample_run("run-a")
    outcomes = {r.scenario_id: r.observed_outcome for r in run.scenarios}
    fetch, calls = fake_fetch("run-a", outcomes)

    ok, text = check(run, fetch)

    print(text)
    assert ok
    assert "Experiments named run-a: 1" in text
    assert "Items: 31 of 31 scenarios" in text
    assert "Outcomes equal to the record: 31 of 31" in text
    assert all("/traces" not in path for path, _ in calls)
    assert calls[0][1]["name"] == "run-a" and "fromStartTime" in calls[0][1]


def test_missing_items_and_outcome_mismatch_reported(tmp_path: Path):
    run = sample_run("run-a")
    outcomes = {r.scenario_id: r.observed_outcome for r in run.scenarios}
    outcomes.pop("AP-1")
    outcomes["BK-1"] = "handoff"
    fetch, _ = fake_fetch("run-a", outcomes)

    ok, text = check(run, fetch)

    print(text)
    assert not ok
    assert "Items: 30 of 31 scenarios" in text
    assert "Outcomes equal to the record: 29 of 31" in text
    assert "  AP-1: missing in Langfuse" in text
    assert "  BK-1: record contained, Langfuse handoff" in text


def test_cli_without_keys_says_so(tmp_path: Path, monkeypatch, capsys):
    from app.evals.langfuse_check import main

    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    record = write_run(tmp_path / "run.json", sample_run("run-a"))
    assert main([str(record)]) == 1
    assert "LANGFUSE_PUBLIC_KEY" in capsys.readouterr().err
