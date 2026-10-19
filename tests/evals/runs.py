"""A run record over the real eval scenarios, built by hand for the printing tests."""

from pathlib import Path

from app.evals.records import (
    Judge,
    RunResult,
    ScenarioResult,
    TranscriptLine,
    load_scenarios,
)
from app.evals.summary import compute_summary
from app.settings import REPO_ROOT

SCENARIOS = load_scenarios(REPO_ROOT / "eval" / "scenarios")
WEIGHTS = {
    "booking": 120,
    "warranty": 45,
    "billing": 42,
    "membership": 38,
    "appointment": 29,
}
AFTER = Path(__file__).parent / "fixtures" / "runs" / "after.json"
HANDLED = sorted(
    s.id for s in SCENARIOS if s.driver in WEIGHTS and s.kind in ("happy", "edge")
)


def _result(sid: str) -> ScenarioResult:
    scenario = next(s for s in SCENARIOS if s.id == sid)
    failing = sid == "BI-2"
    observed = "handoff" if failing else scenario.expected.outcome
    return ScenarioResult(
        scenario_id=sid,
        observed_outcome=observed,
        contained_correct=not failing,
        facts_missing=["the balance"] if failing else [],
        turns=3,
        latencies_ms=[2000, 3000],
        cost_usd=0.01,
        judge=Judge(
            verdict="fail" if failing else "pass",
            notes="JUDGE-NOTES-SECRET-TO-GRADER",
        ),
        handoff_kind="safety_stop" if observed == "safety_stop" else None,
        handoff_reason="gas" if observed == "safety_stop" else None,
        transcript=[
            TranscriptLine(role="caller", text=f"{sid} caller line"),
            TranscriptLine(role="agent", text=f"{sid} agent line", latency_ms=2000),
        ],
    )


def sample_run(run_id: str = "run-sample") -> RunResult:
    base = RunResult.model_validate_json(AFTER.read_bytes())
    results = [_result(s.id) for s in SCENARIOS]
    return RunResult(
        run_id=run_id,
        started_at="2026-10-19T09:00:00Z",
        finished_at="2026-10-19T09:07:05Z",
        duration_s=425.0,
        workers=4,
        environment=base.environment,
        scenarios=results,
        summary=compute_summary(SCENARIOS, results, WEIGHTS, {}),
    )


def write_run(path: Path, run: RunResult) -> Path:
    path.write_text(run.model_dump_json(by_alias=True, indent=2))
    return path
