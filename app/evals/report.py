"""python -m app.evals.report RUN.json — read an existing run record again.

Prints the run's summary with judge agreement recomputed from a grades file that names this
run (EV-5). `--transcripts handled` prints what a builder needs to grade the handled-driver
scenarios blind: the scenario, what changed and the conversation, never the judge's verdict
or the pass/fail. `--grades-template` prints an empty grades file for those scenarios.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.evals.compare import read_run
from app.evals.records import RunResult, Scenario, load_scenarios, load_weights
from app.evals.run import format_summary
from app.evals.summary import (
    HANDLED_KINDS,
    grades_for,
    judge_agreement,
    load_human_grades,
)
from app.settings import REPO_ROOT


def _handled(scenarios: Sequence[Scenario], weights: dict[str, int]) -> list[Scenario]:
    return [s for s in scenarios if s.driver in weights and s.kind in HANDLED_KINDS]


def _rows(diff: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for table, entry in diff.items():
        lines += [
            f"  {table} added {json.dumps(row)}" for row in entry.get("added", [])
        ]
        for c in entry.get("changed", []):
            changed = {
                k: [c["before"].get(k), v]
                for k, v in c["after"].items()
                if c["before"].get(k) != v
            }
            lines.append(f"  {table} {c['key']} changed {json.dumps(changed)}")
        lines += [
            f"  {table} removed {json.dumps(row)}" for row in entry.get("removed", [])
        ]
    return lines or ["  none"]


def transcripts(run: RunResult, scenarios: Sequence[Scenario]) -> str:
    """Each scenario as a grader sees it; no judge output, no pass or fail."""
    by_id = {r.scenario_id: r for r in run.scenarios}
    blocks: list[str] = []
    for s in scenarios:
        r = by_id.get(s.id)
        if r is None:
            continue
        db = s.expected.db_change
        lines = [
            f"=== {s.id} ({s.driver}, {s.kind}): {s.title}",
            f"Expected outcome: {s.expected.outcome}",
            "Expected facts:",
            *[f"  - {fact}" for fact in s.expected.facts],
            "Forbidden: " + (", ".join(s.expected.forbidden) or "none"),
            "Expected database change: " + (db.detail if db else "not checked"),
            f"Observed outcome: {r.observed_outcome}",
            "Database difference:",
            *_rows(r.db_diff),
            "Transcript:",
            *[f"  {line.role.upper()}: {line.text}" for line in r.transcript],
            "",
        ]
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.evals.report")
    parser.add_argument("run", type=Path)
    parser.add_argument(
        "--grades", type=Path, default=REPO_ROOT / "eval" / "human_grades.json"
    )
    parser.add_argument(
        "--scenarios", type=Path, default=REPO_ROOT / "eval" / "scenarios"
    )
    parser.add_argument(
        "--weights", type=Path, default=REPO_ROOT / "eval" / "weights.json"
    )
    parser.add_argument("--transcripts", choices=("handled", "all"))
    parser.add_argument("--grades-template", action="store_true")
    args = parser.parse_args(argv)

    run = read_run(args.run)
    if run is None:
        sys.stderr.write(f"Cannot read run file: {args.run}\n")
        return 1
    scenarios = load_scenarios(args.scenarios)
    weights = load_weights(args.weights)
    handled = _handled(scenarios, weights)
    if args.grades_template:
        template = {"runId": run.run_id, "grades": {s.id: "" for s in handled}}
        sys.stdout.write(json.dumps(template, indent=2) + "\n")
        return 0
    if args.transcripts:
        shown = handled if args.transcripts == "handled" else scenarios
        sys.stdout.write(transcripts(run, shown))
        return 0
    try:
        human = load_human_grades(args.grades)
    except ValueError as error:
        sys.stderr.write(f"{error}\n")
        return 1
    by_id = {r.scenario_id: r for r in run.scenarios}
    agreement = judge_agreement(
        scenarios, by_id, weights, grades_for(run.run_id, human)
    )
    if agreement is not None:
        run.summary.judge_agreement = agreement
    text = format_summary(
        run,
        human is not None,
        grades_run=human.run_id if human else None,
        scenarios=scenarios,
    )
    sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
