from app.evals.records import (
    Expected,
    Scenario,
    ScenarioResult,
    TranscriptLine,
)
from app.evals.summary import compute_summary

WEIGHTS = {
    "booking": 120,
    "warranty": 45,
    "billing": 42,
    "membership": 38,
    "appointment": 29,
}


def scenario(sid: str, driver: str, kind: str, outcome: str = "contained", **extra):
    return Scenario(
        id=sid,
        driver=driver,
        kind=kind,  # type: ignore[arg-type]
        opening="hi",
        expected=Expected(outcome=outcome),  # type: ignore[arg-type]
        **extra,
    )


def result(sid: str, observed: str = "contained", ok: bool = True, **extra):
    return ScenarioResult(
        scenario_id=sid,
        observed_outcome=observed,  # type: ignore[arg-type]
        contained_correct=ok,
        **extra,
    )


def fixture(billing_miss: bool = True, escalation_ok: bool = True):
    scenarios, results = [], []
    for driver in WEIGHTS:
        for n, kind in enumerate(("happy", "edge")):
            sid = f"{driver}-{n}"
            scenarios.append(scenario(sid, driver, kind))
            miss = billing_miss and sid == "billing-0"
            results.append(result(sid, "handoff" if miss else "contained", ok=not miss))
    for n in range(3):
        scenarios.append(scenario(f"esc-{n}", "escalate", "escalation", "handoff"))
        results.append(
            result(
                f"esc-{n}",
                "handoff" if escalation_ok else "contained",
                ok=escalation_ok,
            )
        )
    return scenarios, results


def test_projected_containment_vr1():
    scenarios, results = fixture()
    summary = compute_summary(scenarios, results, WEIGHTS, {})
    print(summary.projected_containment_pct, summary.weighting)
    assert summary.projected_containment_pct == 60.2
    rows = {w.driver: w for w in summary.weighting}
    assert (rows["booking"].scenarios_contained, rows["booking"].scenarios_total) == (
        2,
        2,
    )
    assert (rows["billing"].scenarios_contained, rows["billing"].scenarios_total) == (
        1,
        2,
    )
    assert rows["billing"].contribution_pct == 5.0
    assert summary.handled_accuracy.passed == 9 and summary.handled_accuracy.of == 10

    # Escalation scenarios never enter the sum.
    scenarios, results = fixture(escalation_ok=False)
    assert (
        compute_summary(scenarios, results, WEIGHTS, {}).projected_containment_pct
        == 60.2
    )
    scenarios, results = fixture(billing_miss=False)
    assert (
        compute_summary(scenarios, results, WEIGHTS, {}).projected_containment_pct
        == 65.2
    )


def test_summary_counts():
    book = scenario("B", "booking", "happy", customer_id="MHC-10001")
    safe = scenario("S", "safety", "safety", "safety_stop")
    esc = scenario("E", "escalate", "escalation", "handoff")
    bad = scenario("X", "billing", "happy")
    leak = scenario("L", "billing", "edge", customer_id="MHC-10002")
    scenarios = [book, safe, esc, bad, leak]
    agent = lambda text, ms, write=False: TranscriptLine(
        role="agent", text=text, latency_ms=ms, has_write=write
    )
    results = [
        result(
            "B",
            turns=4,
            latencies_ms=[100, 900],
            transcript=[agent("hi", 100), agent("booked", 900, True)],
            db_diff={"appointments": {"added": [{"customer_id": "MHC-10001"}]}},
        ),
        result("S", "safety_stop", True),
        result("E", "handoff", True),
        result("X", "error", False, error="boom"),
        result(
            "L",
            ok=False,
            forbidden_hits=["old price"],
            unsupported_figures=2,
            invariant_violations=1,
            transcript=[agent("Linda Foster is booked Monday", 50)],
            latencies_ms=[50],
            turns=2,
        ),
    ]
    s = compute_summary(
        scenarios,
        results,
        WEIGHTS,
        {"MHC-10001": ["Linda Foster"], "MHC-10002": ["Omar Patel"]},
    )
    assert (s.escalation.handed_off, s.escalation.of) == (1, 1)
    assert (s.safety.passed, s.safety.of) == (1, 1)
    assert (s.seeded_customers.passed, s.seeded_customers.of) == (1, 4)
    assert s.cross_account_leaks == 1
    assert s.superseded_or_internal_hits == 1
    assert s.unsupported_figures == 2 and s.invariant_violations == 1
    assert s.errored == 1 and s.errored_ids == ["X"]
    assert s.contained_wrong == 1
    assert s.latency.first_reply_p95_ms == 100
    assert s.latency.write_turn_p95_ms == 900
    assert s.latency.median_booking_turns == 4.0
    assert s.judge_agreement is None


def test_median_booking_turns_ignores_the_booking_escalation():
    scenarios = [
        scenario("B1", "booking", "happy"),
        scenario("B2", "booking", "edge"),
        scenario("B3", "booking", "escalation", "handoff"),
    ]
    results = [
        result("B1", turns=4),
        result("B2", turns=6),
        result("B3", "handoff", turns=20),
    ]
    summary = compute_summary(scenarios, results, WEIGHTS, {})
    assert summary.latency.median_booking_turns == 5.0
