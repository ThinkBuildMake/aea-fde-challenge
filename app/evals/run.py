"""The eval command: python -m app.evals.run [--scenarios DIR] [--weights FILE] [--workers N]
[--grades FILE]."""

import argparse
import sys
import tempfile
from pathlib import Path

from app.evals.caller import OpenRouterCaller
from app.evals.environment import describe_environment
from app.evals.judge import OpenRouterJudge
from app.evals.langfuse_report import langfuse_reporter
from app.evals.records import RunResult, load_scenarios, load_weights
from app.evals.runner import make_run_id, run_eval
from app.evals.summary import load_human_grades
from app.knowledge.embeddings import OpenRouterEmbedder
from app.llm import OpenRouterProvider
from app.settings import REPO_ROOT, load_settings_or_exit


def _fraction(passed: int, of: int) -> str:
    return f"{passed} of {of}"


def format_summary(run: RunResult) -> str:
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
        "",
        f"Projected containment: {s.projected_containment_pct}%",
    ]
    lines += [
        f"  {w.driver:<12} {w.calls:>4} calls  {w.scenarios_contained}/{w.scenarios_total} "
        f"contained  {w.contribution_pct}%"
        for w in s.weighting
    ]
    lines += [
        f"Handled accuracy: {_fraction(s.handled_accuracy.passed, s.handled_accuracy.of)}",
        "Judge agreement: "
        + (
            _fraction(s.judge_agreement.agreed, s.judge_agreement.of)
            if s.judge_agreement
            else "not computed (no human grades)"
        ),
        f"Escalation handed off: {_fraction(s.escalation.handed_off, s.escalation.of)}",
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
    judge = OpenRouterJudge(settings)
    with tempfile.TemporaryDirectory(prefix="meridian-eval-") as work:
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
            run_id=run_id,
            judge=judge,
            human_grades=human_grades,
        )
    judge.close()
    sys.stdout.write(format_summary(run) + f"\n\nRecord written to {out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
