import json
from pathlib import Path

from app.evals.report import main
from tests.evals.runs import HANDLED, sample_run, write_run


def grades_file(path: Path, run_id: str, fail: tuple[str, ...] = ()) -> Path:
    grades = {sid: "fail" if sid in fail else "pass" for sid in HANDLED}
    path.write_text(json.dumps({"runId": run_id, "grades": grades}))
    return path


def test_report_recomputes_agreement_for_its_run(tmp_path: Path, capsys):
    record = write_run(tmp_path / "run.json", sample_run("run-a"))
    # The builder failed BI-2 (the judge did too) and AP-1 (the judge passed it).
    grades = grades_file(tmp_path / "grades.json", "run-a", fail=("BI-2", "AP-1"))

    code = main([str(record), "--grades", str(grades)])

    out = capsys.readouterr().out
    print(out)
    assert code == 0
    assert "Judge agreement: 9 of 10" in out
    assert "  BI-2  billing" in out


def test_report_ignores_grades_of_another_run(tmp_path: Path, capsys):
    record = write_run(tmp_path / "run.json", sample_run("run-b"))
    grades = grades_file(tmp_path / "grades.json", "run-a")

    main([str(record), "--grades", str(grades)])

    out = capsys.readouterr().out
    assert "Judge agreement: not computed (grades are for run run-a" in out


def test_transcripts_hide_the_judge_verdict(tmp_path: Path, capsys):
    record = write_run(tmp_path / "run.json", sample_run("run-a"))

    code = main([str(record), "--transcripts", "handled"])

    out = capsys.readouterr().out
    print(out[:1500])
    assert code == 0
    blocks = [b for b in out.split("=== ") if b.strip()]
    assert sorted(b.split()[0] for b in blocks) == HANDLED
    bi2 = next(b for b in blocks if b.startswith("BI-2"))
    assert "Expected facts:" in bi2 and "Observed outcome: handoff" in bi2
    assert "CALLER: BI-2 caller line" in bi2 and "AGENT: BI-2 agent line" in bi2
    for hidden in ("JUDGE-NOTES-SECRET-TO-GRADER", "verdict", "PASS", "FAIL"):
        assert hidden not in out


def test_grades_template_lists_the_ten_handled(tmp_path: Path, capsys):
    record = write_run(tmp_path / "run.json", sample_run("run-a"))

    main([str(record), "--grades-template"])

    template = json.loads(capsys.readouterr().out)
    print(template)
    assert template["runId"] == "run-a"
    assert sorted(template["grades"]) == HANDLED and len(HANDLED) == 10
    assert set(template["grades"].values()) == {""}


def test_unreadable_record_is_named(tmp_path: Path, capsys):
    missing = tmp_path / "missing.json"
    assert main([str(missing)]) == 1
    assert capsys.readouterr().err == f"Cannot read run file: {missing}\n"
