from app.evals.run import format_summary
from tests.evals.runs import SCENARIOS, sample_run


def test_summary_lists_every_scenario_with_pass_or_fail():
    run = sample_run()

    text = format_summary(run, scenarios=SCENARIOS)

    print(text)
    lines = text.splitlines()
    rows = [
        x
        for x in lines
        if x.endswith(("PASS", "FAIL")) or " PASS " in x or " FAIL " in x
    ]
    assert len(rows) == 31
    (bi2,) = [x for x in rows if x.split()[0] == "BI-2"]
    assert "expected contained" in bi2 and "observed handoff" in bi2 and "FAIL" in bi2
    assert "facts missing 1" in bi2
    (sf1,) = [x for x in rows if x.split()[0] == "SF-1"]
    assert "observed safety_stop" in sf1 and "PASS" in sf1
    assert "handoff safety_stop/gas" in sf1


def test_summary_prints_duration_and_new_counters():
    text = format_summary(sample_run(), scenarios=SCENARIOS)

    assert "Finished in 7 min 5 s with 4 workers" in text
    assert "Handoff records complete: 0 of 15" in text
    assert "Unconfirmed changes: 0" in text


def test_grades_for_other_run_are_named():
    text = format_summary(sample_run("run-b"), grades_run="run-a")

    assert (
        "Judge agreement: not computed (grades are for run run-a; "
        "see python -m app.evals.report)"
    ) in text
