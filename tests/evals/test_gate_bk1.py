"""The gate keeps one eval case for real (S41 criterion 10): runEval plays the shipped BK-1
scenario through the real app on a private copy of the seed, with only the agent model
scripted (a recording-shaped booking for Grace Okafor) and the caller replaying her yes."""

from pathlib import Path

from app.evals.caller import ScriptedCaller
from app.evals.records import load_scenarios, load_weights
from app.evals.runner import run_eval
from app.llm import FakeModelProvider, ModelResult
from app.settings import REPO_ROOT, Settings
from tests.evals.helpers import environment, sha
from tests.gate.test_change_a_visit import call, turn

YES = "Yes, Monday 12 to 4 works, book it."
BOOKED = (
    "You are booked for Monday October 19, 12 PM to 4 PM with Tasha Bell. "
    "As a Plus member, your diagnostic fee is waived."
)


def grace_books_monday() -> list[ModelResult]:
    return [
        *turn(
            [
                call(
                    "id", "identify_customer", name="Grace Okafor", phone="512-555-0103"
                ),
                call(
                    "w",
                    "find_open_windows",
                    serviceType="hvac_repair",
                    preferredDate="2026-10-19",
                ),
                call("s", "report_status", intent="book_visit", resolved=False),
            ],
            "Thanks, Grace. Monday October 19, 12 PM to 4 PM with Tasha Bell is open. "
            "Shall I book it?",
        ),
        *turn(
            [
                call(
                    "b",
                    "book_visit",
                    slotId=45,
                    issue="Lennox AC runs but blows warm air",
                    callerQuote=YES,
                )
            ],
            BOOKED,
        ),
    ]


def test_bk1_passes_with_its_database_change(live: Settings, tmp_path: Path):
    (bk1,) = [
        s for s in load_scenarios(REPO_ROOT / "eval" / "scenarios") if s.id == "BK-1"
    ]
    seed_before = sha(live.SEED_DB_PATH)
    model = FakeModelProvider(results=grace_books_monday())

    run = run_eval(
        [bk1],
        load_weights(REPO_ROOT / "eval" / "weights.json"),
        settings=live,
        out_path=tmp_path / "runs" / "bk1.json",
        work_dir=tmp_path / "work",
        agent_model=lambda scenario: model,
        caller=ScriptedCaller({"BK-1": [YES]}),
        environment=environment(live),
        workers=1,
        judge=None,
    )

    (r,) = run.scenarios
    (added,) = r.db_diff["appointments"]["added"]
    print(
        f"BK-1 observed={r.observed_outcome} containedCorrect={r.contained_correct} "
        f"added slot={added['slot_id']} customer={added['customer_id']} "
        f"mismatches={r.db_change_mismatches} invariants={r.invariant_violations}"
    )
    assert r.observed_outcome == "contained" and r.contained_correct
    assert r.db_change_mismatches == [] and r.invariant_violations == 0
    assert added["slot_id"] in (45, 63) and added["customer_id"] == "MHC-10003"
    assert sha(live.SEED_DB_PATH) == seed_before
