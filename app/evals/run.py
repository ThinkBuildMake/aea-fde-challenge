"""The eval command: python -m app.evals.run [--scenarios DIR] [--weights FILE] [--workers N]
[--grades FILE]."""

import argparse
import sys
import tempfile
from collections.abc import Sequence
from contextlib import closing
from pathlib import Path

from app.evals.caller import OpenRouterCaller
from app.evals.environment import describe_environment
from app.evals.judge import OpenRouterJudge
from app.evals.langfuse_report import langfuse_reporter
from app.evals.records import (
    RunResult,
    Scenario,
    ScenarioResult,
    load_scenarios,
    load_weights,
)
from app.evals.runner import make_run_id, run_eval
from app.evals.summary import grades_for, load_human_grades
from app.knowledge.embeddings import OpenRouterEmbedder
from app.llm import OpenRouterProvider
from app.settings import REPO_ROOT, load_settings_or_exit


def _fraction(passed: int, of: int) -> str:
    return f"{passed} of {of}"


def _why(result: ScenarioResult, scenario: Scenario | None) -> list[str]:
    """What made a scenario fail, in a few words each."""
    if result.error:
        return [f"error {result.error.split(':')[0]}"]
    why: list[str] = []
    if scenario is not None and result.observed_outcome != scenario.expected.outcome:
        why.append("outcome")
    if result.facts_missing:
        why.append(f"facts missing {len(result.facts_missing)}")
    if result.judge.contradictions:
        why.append(f"contradictions {len(result.judge.contradictions)}")
    if result.judge.verdict == "error":
        why.append("judge error")
    if result.forbidden_hits:
        why.append(f"forbidden {', '.join(result.forbidden_hits)}")
    if result.unsupported_figures:
        why.append(f"unsupported figures {result.unsupported_figures}")
    if result.invariant_violations:
        why.append(f"invariants {result.invariant_violations}")
    if result.db_change_mismatches:
        why.append(f"db change {'; '.join(result.db_change_mismatches)}")
    if result.unconfirmed_changes:
        why.append(f"unconfirmed changes {result.unconfirmed_changes}")
    return why


def scenario_lines(run: RunResult, scenarios: Sequence[Scenario] = ()) -> list[str]:
    """One line per scenario: what was expected, what happened, PASS or FAIL and why."""
    known = {s.id: s for s in scenarios}
    lines: list[str] = []
    for r in run.scenarios:
        s = known.get(r.scenario_id)
        head = f"  {r.scenario_id:<5} "
        if s is not None:
            head += f"{s.driver:<11} {s.kind:<10} expected {s.expected.outcome:<11} "
        line = (
            f"{head}observed {r.observed_outcome:<11} "
            f"{'PASS' if r.contained_correct else 'FAIL'}"
        )
        if r.handoff_kind:
            line += f"  handoff {r.handoff_kind}/{r.handoff_reason}"
        if not r.contained_correct:
            line += "  (" + "; ".join(_why(r, s) or ["see record"]) + ")"
        lines.append(line)
    return lines


def _judge_line(run: RunResult, grades_loaded: bool, grades_run: str | None) -> str:
    s = run.summary
    if s.judge_agreement:
        return _fraction(s.judge_agreement.agreed, s.judge_agreement.of)
    if grades_run is not None and grades_run != run.run_id:
        return (
            f"not computed (grades are for run {grades_run}; "
            "see python -m app.evals.report)"
        )
    if grades_loaded or grades_run is not None:
        return "not computed (grades file has no scenarios from this run)"
    return "not computed (no human grades)"


def format_summary(
    run: RunResult,
    grades_loaded: bool = False,
    *,
    grades_run: str | None = None,
    scenarios: Sequence[Scenario] = (),
) -> str:
    """`grades_loaded`: a human grades file was read, so a null judgeAgreement means it
    graded none of this run's handled-driver scenarios; `grades_run` is the run it graded."""
    s = run.summary
    env = run.environment
    latency = s.latency
    lines = [
        f"Run {run.run_id} at {run.started_at}",
        (
            f"Agent {env.agent_model}, caller {env.caller_model}, "
            f"index {env.kb_index_version}, snapshot {env.db_snapshot_id[:19]}, "
            f"commit {env.app_commit[:12]}"
        ),
    ]
    if run.duration_s is not None:
        minutes, seconds = divmod(round(run.duration_s), 60)
        lines.append(
            f"Finished in {minutes} min {seconds} s with {run.workers or '?'} workers"
        )
    lines += ["", f"Scenarios ({len(run.scenarios)}):", *scenario_lines(run, scenarios)]
    lines += ["", f"Projected containment: {s.projected_containment_pct}%"]
    lines += [
        f"  {w.driver:<12} {w.calls:>4} calls  {w.scenarios_contained}/{w.scenarios_total} "
        f"contained  {w.contribution_pct}%"
        for w in s.weighting
    ]
    complete = s.handoff_records_complete
    lines += [
        f"Handled accuracy: {_fraction(s.handled_accuracy.passed, s.handled_accuracy.of)}",
        "Judge agreement: " + _judge_line(run, grades_loaded, grades_run),
        f"Escalation handed off: {_fraction(s.escalation.handed_off, s.escalation.of)}",
        "Handoff records complete: "
        + (_fraction(complete.passed, complete.of) if complete else "not recorded"),
        f"Safety: {_fraction(s.safety.passed, s.safety.of)}",
        f"Cross-account leaks: {s.cross_account_leaks}",
        f"Superseded or internal hits: {s.superseded_or_internal_hits}",
        f"Seeded customers booked: {_fraction(s.seeded_customers.passed, s.seeded_customers.of)}",
        (
            f"Latency: first reply p95 {latency.first_reply_p95_ms} ms, write turn p95 "
            f"{latency.write_turn_p95_ms} ms, median booking turns "
            f"{latency.median_booking_turns}"
        ),
        f"Contained wrong: {s.contained_wrong}",
        f"Unsupported figures: {s.unsupported_figures}",
        f"Unconfirmed changes: {s.unconfirmed_changes}",
        f"Invariant violations: {s.invariant_violations}",
        f"Database-change mismatches: {s.db_change_mismatches}",
        f"Errored: {s.errored}"
        + (f" ({', '.join(s.errored_ids)})" if s.errored else ""),
        f"Cost: ${sum(r.cost_usd for r in run.scenarios):.2f} over {len(run.scenarios)} scenarios",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.evals.run")
    parser.add_argument(
        "--scenarios", type=Path, default=REPO_ROOT / "eval" / "scenarios"
    )
    parser.add_argument(
        "--weights", type=Path, default=REPO_ROOT / "eval" / "weights.json"
    )
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--grades", type=Path, default=REPO_ROOT / "eval" / "human_grades.json"
    )
    args = parser.parse_args(argv)

    settings = load_settings_or_exit()
    try:
        human_grades = load_human_grades(args.grades)
    except ValueError as error:
        sys.stderr.write(f"{error}\n")
        return 1
    scenarios = load_scenarios(args.scenarios)
    if not scenarios:
        sys.stderr.write(f"No scenario files in {args.scenarios}\n")
        return 1
    run_id = make_run_id()
    out = args.out or REPO_ROOT / "eval" / "runs" / f"{run_id}.json"
    provider = OpenRouterProvider(settings)
    with (
        closing(OpenRouterJudge(settings)) as judge,
        tempfile.TemporaryDirectory(prefix="meridian-eval-") as work,
    ):
        run = run_eval(
            scenarios,
            load_weights(args.weights),
            settings=settings,
            out_path=out,
            work_dir=Path(work) / "workers",
            agent_model=lambda scenario: provider,
            caller=OpenRouterCaller(settings),
            environment=describe_environment(
                settings, settings.SEED_DB_PATH, settings.INDEX_PATH
            ),
            workers=args.workers,
            embedder=OpenRouterEmbedder(settings),
            reporter=langfuse_reporter(settings),
            reporter_timeout_s=300,
            run_id=run_id,
            judge=judge,
            human_grades=grades_for(run_id, human_grades),
        )
    text = format_summary(
        run,
        human_grades is not None,
        grades_run=human_grades.run_id if human_grades else None,
        scenarios=scenarios,
    )
    sys.stdout.write(text + f"\n\nRecord written to {out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
