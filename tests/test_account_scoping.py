"""AZ-1 and AZ-2: the account always comes from the conversation."""

from typing import Any

import pytest

from app.conversation import tools
from app.settings import Settings
from tests.test_agent_tools import (
    Recorder,
    booking,
    customer,
    identify_and_offer,
    run,
    stub,
    tool_call,
    tool_results,
)

ACCOUNT_CALLS: dict[str, dict[str, Any]] = {
    "find_open_windows": {"serviceType": "hvac_repair"},
    "lookup_my_appointments": {},
    "book_visit": {"slotId": 3, "issue": "x", "callerQuote": "yes"},
    "move_visit": {"appointmentId": 7, "newSlotId": 3, "callerQuote": "yes"},
    "cancel_visit": {"appointmentId": 7, "callerQuote": "yes"},
    "get_my_billing": {},
    "send_payment_link": {"invoiceId": "INV-1"},
    "join_waitlist": {"appointmentId": 7},
}
SCHEDULING = [
    "find_open_windows",
    "list_appointments",
    "book_visit",
    "move_visit",
    "cancel_visit",
    "get_billing",
    "create_payment_link",
    "get_appointment",
]


def watch_everything(monkeypatch: pytest.MonkeyPatch) -> list[Recorder]:
    recorders = [
        stub(monkeypatch, f"app.scheduling.service.{name}", None) for name in SCHEDULING
    ]
    recorders.append(stub(monkeypatch, "app.followups.service.join_waitlist", None))
    return recorders


def test_no_tool_takes_an_account_from_the_model():
    for spec in tools.TOOLS:
        for prop in spec["function"]["parameters"]["properties"]:
            assert "customer" not in prop.lower()
            assert "conversation" not in prop.lower()


@pytest.mark.parametrize("name", list(ACCOUNT_CALLS))
def test_every_account_tool_waits_for_a_match(
    started: Settings, monkeypatch: pytest.MonkeyPatch, name: str
):
    recorders = watch_everything(monkeypatch)
    cid, _ = run(started, [tool_call("x", name, **ACCOUNT_CALLS[name])])
    assert all(r.calls == [] for r in recorders)
    assert tool_results(started, cid)[0]["error"] == "not_identified"


@pytest.mark.parametrize("name", ["book_visit", "move_visit", "cancel_visit"])
def test_writes_touch_only_the_matched_account(
    started: Settings, monkeypatch: pytest.MonkeyPatch, name: str
):
    stub(monkeypatch, "app.scheduling.service.identify_customer", customer("MHC-10002"))
    recorders = watch_everything(monkeypatch)
    for r in recorders:
        r.value = booking()  # failures after the call are fine; only the ids matter
    run(
        started,
        identify_and_offer(monkeypatch, "MHC-10002"),
        [tool_call("w", name, customerId="MHC-10001", **ACCOUNT_CALLS[name])],
        texts=["hi", "yes"],
    )
    seen = [c[1] for r in recorders for c in r.calls if len(c) > 1]
    assert seen == ["MHC-10002"]
