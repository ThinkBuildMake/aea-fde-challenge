import json
from typing import Any

import pytest

from app.llm import FakeModelProvider
from app.settings import Settings
from app.types import (
    AppointmentView,
    Booking,
    CancelResult,
    CustomerRef,
    Fee,
    OpenWindows,
    Window,
)
from tests.test_turn import (
    assistant,
    client_for,
    new_conversation,
    result,
    rows,
    say,
    tool_call,
)


class Recorder:
    def __init__(self, value: Any = None) -> None:
        self.value = value
        self.calls: list[tuple[Any, ...]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(args)
        return self.value


def stub(monkeypatch: pytest.MonkeyPatch, path: str, value: Any) -> Recorder:
    recorder = Recorder(value)
    monkeypatch.setattr(path, recorder)
    return recorder


def customer(customer_id: str, tier: str = "none") -> CustomerRef:
    return CustomerRef(
        customer_id=customer_id,
        name="Test",
        city="Austin",
        zone="south",
        membership_tier=tier,  # type: ignore[arg-type]
        membership_renewal_date=None,
        system_brand=None,
        system_install_date=None,
    )


def window(slot_id: int, start: str = "08:00", end: str = "12:00") -> Window:
    return Window(
        slot_id=slot_id,
        date="2026-10-21",
        window=f"{start}-{end}",
        service_type="hvac_repair",
        zone="south",
        technician_name="Jun Park",
        member_only=False,
    )


def booking() -> Booking:
    return Booking(
        appointment_id=7,
        slot_id=3,
        date="2026-10-21",
        window="08:00-12:00",
        technician_name="Jun Park",
        service_type="hvac_repair",
        zone="south",
        diagnostic_fee_cents=0,
        diagnostic_fee_waived=False,
    )


def run(
    started: Settings, *steps: list[dict[str, Any]], texts: list[str] | None = None
):
    """One turn per step: the model makes the step's calls, then answers."""
    results = []
    for i, calls in enumerate(steps):
        results.append(result(assistant(calls=calls)))
        results.append(result(assistant(f"answer {i}")))
    client = client_for(started, FakeModelProvider(results=results))
    cid = new_conversation(client)
    replies = [
        say(client, cid, (texts or [])[i] if texts else f"message {i}")
        for i in range(len(steps))
    ]
    return cid, replies


def tool_results(started: Settings, cid: str) -> list[dict[str, Any]]:
    out = []
    for turn in rows(
        started, "SELECT model_messages FROM turns WHERE conversation_id = ?", cid
    ):
        out += [
            json.loads(m["content"])
            for m in json.loads(turn["model_messages"])
            if m["role"] == "tool"
        ]
    return out


def identify(customer_id: str) -> list[dict[str, Any]]:
    call = tool_call("id", "identify_customer")
    call["function"]["arguments"] = json.dumps({"name": "Test"})
    return [call]


def test_account_tools_use_the_matched_customer(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    stub(monkeypatch, "app.scheduling.service.identify_customer", customer("MHC-10002"))
    billing = stub(monkeypatch, "app.scheduling.service.get_billing", None)
    from app.types import Billing, PaymentLink

    billing.value = Billing(balance_cents=0, invoices=[])
    link = stub(
        monkeypatch,
        "app.scheduling.service.create_payment_link",
        PaymentLink(url="https://pay", valid_for_hours=24),
    )
    appts = stub(monkeypatch, "app.scheduling.service.list_appointments", [])
    other = {"customerId": "MHC-10001"}
    run(
        started,
        identify("MHC-10002"),
        [
            tool_call("a", "get_my_billing", **other),
            tool_call("b", "send_payment_link", invoiceId="INV-1", **other),
            tool_call("c", "lookup_my_appointments", **other),
        ],
    )
    for recorder in (billing, link, appts):
        assert [c[1] for c in recorder.calls] == ["MHC-10002"]


def test_account_tools_wait_for_a_match(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    billing = stub(monkeypatch, "app.scheduling.service.get_billing", None)
    cid, _ = run(started, [tool_call("a", "get_my_billing")])
    assert billing.calls == []
    out = tool_results(started, cid)[0]
    assert out["ok"] is False and out["error"] == "not_identified"
    assert "not identified" in out["message"]


def test_identification_is_capped(started: Settings, monkeypatch: pytest.MonkeyPatch):
    ident = stub(monkeypatch, "app.scheduling.service.identify_customer", None)
    cid, _ = run(
        started,
        *[identify("X") for _ in range(4)],
    )
    assert len(ident.calls) == 3
    last = tool_results(started, cid)[-1]
    assert last["error"] == "identify_limit_reached" and "escalate" in last["message"]
    assert rows(started, "SELECT identify_attempts FROM conversations")[0][0] == 3


def test_window_choices_come_from_the_tool_result(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    stub(monkeypatch, "app.scheduling.service.identify_customer", customer("MHC-10002"))
    found = stub(
        monkeypatch,
        "app.scheduling.service.find_open_windows",
        OpenWindows(
            windows=[
                window(1),
                window(2, "12:00", "16:00"),
                window(3, "16:00", "19:00"),
            ],
            matched_request=True,
            reason=None,
        ),
    )
    _, replies = run(
        started,
        identify("MHC-10002"),
        [tool_call("w", "find_open_windows", serviceType="hvac_repair")],
    )
    assert found.calls[0][1] == "MHC-10002"
    choices = replies[1]["choices"]
    assert [c["label"] for c in choices] == [
        "Wednesday October 21, 8 AM to 12 PM, Jun Park",
        "Wednesday October 21, 12 PM to 4 PM, Jun Park",
        "Wednesday October 21, 4 PM to 7 PM, Jun Park",
        "Nothing earlier? Ask for an earlier window",
    ]
    assert choices[3]["text"] == "Can you do anything earlier?"
    assert choices[0]["text"] == choices[0]["label"]


@pytest.mark.parametrize(
    ("tier", "waived"), [("standard", True), ("plus", True), ("none", False)]
)
def test_member_diagnostic_fee_is_waived_on_the_card(
    started: Settings, monkeypatch: pytest.MonkeyPatch, tier: str, waived: bool
):
    stub(
        monkeypatch,
        "app.scheduling.service.identify_customer",
        customer("MHC-10001", tier),
    )
    stub(monkeypatch, "app.scheduling.service.book_visit", booking())
    stub(
        monkeypatch,
        "app.knowledge.service.get_fee",
        Fee(code="FEE-DIAG", cents=8900, source_file="pricing"),
    )
    _, replies = run(
        started,
        identify("MHC-10001"),
        [tool_call("b", "book_visit", slotId=3, issue="no cooling", callerQuote="yes")],
    )
    card = replies[1]["booking"]
    assert card["diagnosticFeeCents"] == 8900
    assert card["diagnosticFeeWaived"] is waived


def test_late_cancel_carries_the_fee(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    stub(monkeypatch, "app.scheduling.service.identify_customer", customer("MHC-10002"))
    cancel = stub(
        monkeypatch,
        "app.scheduling.service.cancel_visit",
        CancelResult(
            appointment_id=7, freed_slot_id=3, late_fee_applies=True, hours_before=5.0
        ),
    )
    fees = stub(
        monkeypatch,
        "app.knowledge.service.get_fee",
        Fee(code="FEE-LATE", cents=4900, source_file="pricing"),
    )
    cid, _ = run(
        started,
        identify("MHC-10002"),
        [tool_call("c", "cancel_visit", appointmentId=7, callerQuote="yes")],
        texts=["hi", "yes"],
    )
    out = tool_results(started, cid)[-1]
    assert out["lateFeeApplies"] is True and out["lateFeeCents"] == 4900
    assert fees.calls[-1][1] == "FEE-LATE"
    assert cancel.calls[0][1] == "MHC-10002"


def test_waitlist_uses_the_held_window_from_the_database(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    stub(monkeypatch, "app.scheduling.service.identify_customer", customer("MHC-10002"))
    stub(
        monkeypatch,
        "app.scheduling.service.get_appointment",
        AppointmentView(
            appointment_id=7,
            date="2026-10-21",
            window="08:00-12:00",
            technician_name="Jun Park",
            service_type="hvac_repair",
            zone="south",
            issue="x",
            late_cancel_fee_applies=False,
        ),
    )
    waitlist = stub(monkeypatch, "app.followups.service.join_waitlist", None)
    cid, replies = run(
        started,
        identify("MHC-10002"),
        [
            tool_call(
                "j",
                "join_waitlist",
                appointmentId=7,
                date="2026-10-30",
                window="16:00-19:00",
                zone="north",
                serviceType="plumbing",
            )
        ],
    )
    entry = waitlist.calls[0][1]
    assert (entry.held_date, entry.held_window, entry.zone, entry.service_type) == (
        "2026-10-21",
        "08:00-12:00",
        "south",
        "hvac_repair",
    )
    assert entry.conversation_id == cid and entry.customer_id == "MHC-10002"
    assert replies[1]["waitlisted"] is True


def test_handoff_gets_the_conversations_ids(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    stub(monkeypatch, "app.scheduling.service.identify_customer", customer("MHC-10002"))
    handoff = stub(monkeypatch, "app.followups.service.create_handoff", None)
    cid, _ = run(
        started,
        identify("MHC-10002"),
        [
            tool_call(
                "e",
                "escalate",
                kind="handoff",
                reason="caller_asked_for_person",
                intent="other",
                toldCaller="A person will call.",
                conversationId="other",
                customerId="MHC-10001",
                summarySource="system",
            )
        ],
    )
    record = handoff.calls[0][1]
    assert record.conversation_id == cid
    assert record.customer_id == "MHC-10002"
    assert record.summary_source == "agent"
    assert record.stated_name is None and record.stated_phone is None
