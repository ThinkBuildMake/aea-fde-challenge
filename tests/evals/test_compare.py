import subprocess
import sys
from pathlib import Path

import pytest

from app.evals.compare import main
from app.settings import REPO_ROOT

RUNS = Path(__file__).parent / "fixtures" / "runs"
BEFORE, AFTER = RUNS / "before.json", RUNS / "after.json"

LABELS = (
    "Projected containment",
    "booking contribution",
    "billing contribution",
    "Handled accuracy",
    "Escalation handed off",
    "Judge agreement",
    "Safety",
    "Cross-account leaks",
    "Superseded or internal hits",
    "Seeded customers booked",
    "First reply p95",
    "Write turn p95",
    "Median booking turns",
    "Contained wrong",
    "Unsupported figures",
    "Unconfirmed changes",
    "Invariant violations",
    "Database-change mismatches",
    "Errored",
)


def test_compare_prints_count_changes_and_bk2(capsys):
    code = main([str(BEFORE), str(AFTER)])

    out, err = capsys.readouterr()
    print(out)
    assert code == 0 and err == ""
    lines = out.splitlines()
    for label in LABELS:
        (line,) = [x for x in lines if x.strip().startswith(label + ":")]
        assert "->" in line, line
    assert "Projected containment: 60.2% -> 74.5% (+14.3)" in lines
    assert "  booking contribution: 14.3% -> 28.6% (+14.3)" in lines
    assert "Handled accuracy: 8 of 10 -> 9 of 10 (+1)" in lines
    assert "Escalation handed off: 2 of 3 -> 3 of 3 (+1)" in lines
    assert "Judge agreement: 8 of 10 -> 9 of 10 (+1)" in lines
    assert "First reply p95: 2400 ms -> 2200 ms (-200)" in lines
    assert "Database-change mismatches: 1 -> 0 (-1)" in lines
    assert "Errored: 0 -> 0 (+0)" in lines
    assert "  BK-2: handoff -> contained (fail -> pass)" in lines
    assert "Pass or fail differs on 1 of 2 scenarios" in lines
    assert not any("BK-1" in x for x in lines)


@pytest.mark.parametrize("broken", ["missing", "not_json", "not_a_run"])
def test_unreadable_file_is_named_and_nothing_else(tmp_path, capsys, broken):
    path = tmp_path / f"{broken}.json"
    if broken == "not_json":
        path.write_text("{not json")
    elif broken == "not_a_run":
        path.write_text('{"runId": "x"}')

    code = main([str(path), str(AFTER)])

    out, err = capsys.readouterr()
    print(repr(out), repr(err))
    assert code == 1
    assert out == ""
    assert err == f"Cannot read run file: {path}\n"


def test_module_entry_point():
    done = subprocess.run(
        [sys.executable, "-m", "app.evals.compare", str(BEFORE), str(AFTER)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert "BK-2: handoff -> contained (fail -> pass)" in done.stdout
