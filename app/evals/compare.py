"""compareEval: python -m app.evals.compare OLD NEW — what changed between two run records.

Prints the change in every summary count and each scenario whose outcome or pass/fail
changed. Writes nothing. An unreadable file is named on stderr and nothing else is printed.
"""

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

from app.evals.records import RunResult, ScenarioResult


def read_run(path: Path) -> RunResult | None:
    try:
        return RunResult.model_validate_json(path.read_bytes())
    except (OSError, ValueError, ValidationError):
        return None


def _number(label: str, old: float | None, new: float | None, unit: str = "") -> str:
    def show(value: float | None) -> str:
        return "none" if value is None else f"{value}{unit}"

    line = f"{label}: {show(old)} -> {show(new)}"
    if old is None or new is None:
        return line
    if isinstance(old, float) or isinstance(new, float):
        return line + f" ({new - old:+.1f})"
    return line + f" ({new - old:+d})"


def _fraction(
    label: str, old: tuple[int, int] | None, new: tuple[int, int] | None
) -> str:
    def show(value: tuple[int, int] | None) -> str:
        return "none" if value is None else f"{value[0]} of {value[1]}"

    line = f"{label}: {show(old)} -> {show(new)}"
    if old is None or new is None:
        return line
    return line + f" ({new[0] - old[0]:+d})"


def _passfail(result: ScenarioResult | None) -> str:
    if result is None:
        return "absent"
    return "pass" if result.contained_correct else "fail"


def compare_runs(old: RunResult, new: RunResult) -> str:
    a, b = old.summary, new.summary
    lines = [
        f"Comparing {old.run_id} -> {new.run_id}",
        "",
        _number(
            "Projected containment",
            a.projected_containment_pct,
            b.projected_containment_pct,
            "%",
        ),
    ]
    old_rows = {w.driver: w.contribution_pct for w in a.weighting}
    new_rows = {w.driver: w.contribution_pct for w in b.weighting}
    for driver in dict.fromkeys([*old_rows, *new_rows]):
        lines.append(
            "  "
            + _number(
                f"{driver} contribution",
                old_rows.get(driver),
                new_rows.get(driver),
                "%",
            )
        )
    old_judge = (
        (a.judge_agreement.agreed, a.judge_agreement.of) if a.judge_agreement else None
    )
    new_judge = (
        (b.judge_agreement.agreed, b.judge_agreement.of) if b.judge_agreement else None
    )
    lines += [
        _fraction(
            "Handled accuracy",
            (a.handled_accuracy.passed, a.handled_accuracy.of),
            (b.handled_accuracy.passed, b.handled_accuracy.of),
        ),
        _fraction(
            "Escalation handed off",
            (a.escalation.handed_off, a.escalation.of),
            (b.escalation.handed_off, b.escalation.of),
        ),
        _fraction("Judge agreement", old_judge, new_judge),
        _fraction(
            "Safety", (a.safety.passed, a.safety.of), (b.safety.passed, b.safety.of)
        ),
        _number("Cross-account leaks", a.cross_account_leaks, b.cross_account_leaks),
        _number(
            "Superseded or internal hits",
            a.superseded_or_internal_hits,
            b.superseded_or_internal_hits,
        ),
        _fraction(
            "Seeded customers booked",
            (a.seeded_customers.passed, a.seeded_customers.of),
            (b.seeded_customers.passed, b.seeded_customers.of),
        ),
        _number(
            "First reply p95",
            a.latency.first_reply_p95_ms,
            b.latency.first_reply_p95_ms,
            " ms",
        ),
        _number(
            "Write turn p95",
            a.latency.write_turn_p95_ms,
            b.latency.write_turn_p95_ms,
            " ms",
        ),
        _number(
            "Median booking turns",
            a.latency.median_booking_turns,
            b.latency.median_booking_turns,
        ),
        _number("Contained wrong", a.contained_wrong, b.contained_wrong),
        _number("Unsupported figures", a.unsupported_figures, b.unsupported_figures),
        _number("Invariant violations", a.invariant_violations, b.invariant_violations),
        _number(
            "Database-change mismatches", a.db_change_mismatches, b.db_change_mismatches
        ),
        _number("Errored", a.errored, b.errored),
        "",
    ]
    before = {r.scenario_id: r for r in old.scenarios}
    after = {r.scenario_id: r for r in new.scenarios}
    changed = []
    for sid in dict.fromkeys([*before, *after]):
        x, y = before.get(sid), after.get(sid)
        if (
            x
            and y
            and (x.observed_outcome, x.contained_correct)
            == (
                y.observed_outcome,
                y.contained_correct,
            )
        ):
            continue
        changed.append(
            f"  {sid}: {x.observed_outcome if x else 'absent'} -> "
            f"{y.observed_outcome if y else 'absent'} ({_passfail(x)} -> {_passfail(y)})"
        )
    lines += (
        ["Scenarios that changed:", *changed] if changed else ["No scenario changed."]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.evals.compare")
    parser.add_argument("old", type=Path)
    parser.add_argument("new", type=Path)
    args = parser.parse_args(argv)
    old, new = read_run(args.old), read_run(args.new)
    if old is None or new is None:
        for path, run in ((args.old, old), (args.new, new)):
            if run is None:
                sys.stderr.write(f"Cannot read run file: {path}\n")
        return 1
    sys.stdout.write(compare_runs(old, new) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
