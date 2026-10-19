"""The turn's rules: what may be offered or written, whatever the scripted model proposes."""

import json
import sqlite3
import threading
from typing import Any

import pytest

from app.conversation import guards
from app.llm import FakeModelProvider, ModelResult
from app.scheduling import service as scheduling
from app.settings import Settings
from app.types import (
    Booking,
    CancelResult,
    Fee,
    HandoffRecord,
    MoveResult,
    OpenWindows,
    Verdict,
    Window,
)
from tests.gate.harness import FakeClock
from tests.test_turn import (
    assistant,
    client_for,
    new_conversation,
    result,
    rows,
    say,
    tool_call,
)

WINDOW = Window(
    slot_id=56,
    date="2026-10-21",
    window="08:00-10:00",
    service_type="hvac_repair",
    zone="north",
    technician_name="Dana Reyes",
    member_only=False,
)
BOOKING = Booking(
    appointment_id=7,
    slot_id=56,
    date="2026-10-21",
    window="8-10",
    technician_name="Dana Reyes",
    service_type="hvac_repair",
    zone="north",
    diagnostic_fee_cents=8900,
    diagnostic_fee_waived=False,
)


def match(settings: Settings, cid: str, customer_id: str = "MHC-10002") -> None:
    """Give the conversation a matched customer, as identify_customer would."""
    conn = sqlite3.connect(settings.APP_DB_PATH)
    conn.execute(
        "UPDATE conversations SET customer_id = ? WHERE id = ?", (customer_id, cid)
    )
    conn.commit()
    conn.close()


def windows_call(call_id: str = "w") -> dict[str, Any]:
    return tool_call(call_id, "find_open_windows", serviceType="hvac_repair")


class Calls:
    """What the Scheduling and Follow-ups stubs received."""

    def __init__(self) -> None:
        self.windows: list[tuple[Any, ...]] = []
        self.books: list[int] = []
        self.moves: list[tuple[int, int]] = []
        self.cancels: list[int] = []
        self.handoffs: list[tuple[Any, HandoffRecord]] = []
        self.screens: list[tuple[str, bool]] = []
        self.book_error: Exception | None = None
        self.verdicts: list[str] = ["safe"]
        self.screen_gate: threading.Event | None = None
        self.screen_after: Any = None


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> Calls:
    c = Calls()

    def screen(ctx, text, recent_turns, follow_up_pending):
        c.screens.append((text, follow_up_pending))
        if c.screen_gate is not None:
            assert c.screen_gate.wait(5)
        if c.screen_after:
            c.screen_after()
        v = c.verdicts.pop(0) if len(c.verdicts) > 1 else c.verdicts[0]
        return Verdict(verdict=v, reason="gas" if v == "emergency" else "no_hazard")  # type: ignore[arg-type]

    def find_windows(ctx, customer_id, service_type, preferred_date, preferred_window):
        c.windows.append((customer_id, service_type))
        return OpenWindows(windows=[WINDOW], matched_request=True, reason=None)

    def book(ctx, customer_id, slot_id, issue):
        c.books.append(slot_id)
        if c.book_error:
            raise c.book_error
        return BOOKING

    def move(ctx, customer_id, appointment_id, new_slot_id):
        c.moves.append((appointment_id, new_slot_id))
        return MoveResult(booking=BOOKING, late_fee_applies=False)

    def cancel(ctx, customer_id, appointment_id):
        c.cancels.append(appointment_id)
        return CancelResult(
            appointment_id=appointment_id,
            freed_slot_id=56,
            late_fee_applies=False,
            hours_before=48.0,
        )

    monkeypatch.setattr("app.safety.service.screen_safety", screen)
    monkeypatch.setattr(
        "app.followups.service.create_handoff",
        lambda tx, record: c.handoffs.append((tx, record)),
    )
    monkeypatch.setattr(
        "app.knowledge.service.get_fee",
        lambda ctx, code: Fee(code=code, cents=8900, source_file="pricing"),
    )
    for name, fn in [
        ("find_open_windows", find_windows),
        ("book_visit", book),
        ("move_visit", move),
        ("cancel_visit", cancel),
    ]:
        monkeypatch.setattr(f"app.scheduling.service.{name}", fn)
    return c


def offer_turn(started: Settings, calls: Calls, model_tail: list[ModelResult]):
    """A client and conversation where turn 1 already offered slot 56."""
    model = FakeModelProvider(
        results=[
            result(assistant(calls=[windows_call()])),
            result(assistant("Tuesday 8-10 is open.")),
            *model_tail,
        ]
    )
    client = client_for(started, model)
    cid = new_conversation(client)
    match(started, cid)
    say(client, cid, "I need a visit")
    return client, cid, model


def book_call(slot: int, quote: str, call_id: str = "b") -> ModelResult:
    return result(
        assistant(
            calls=[
                tool_call(
                    call_id,
                    "book_visit",
                    slotId=slot,
                    issue="no heat",
                    callerQuote=quote,
                )
            ]
        )
    )


def last_tool_result(model: FakeModelProvider) -> dict[str, Any]:
    return json.loads(
        [m for m in model.received[-1] if m["role"] == "tool"][-1]["content"]
    )


def test_emergency_ends_the_conversation(started: Settings, calls: Calls):
    calls.verdicts = ["emergency"]
    model = FakeModelProvider(results=[result(assistant(calls=[windows_call()]))])
    client = client_for(started, model)
    cid = new_conversation(client)
    reply = say(client, cid, "I smell gas")
    assert reply["text"] == guards.emergency_text(matched=False)
    assert reply["banner"] == "safety_stop" and reply["status"] == "safety_stop"
    assert reply["choices"] == [] and reply["booking"] is None
    assert calls.windows == []
    conv = rows(started, "SELECT * FROM conversations WHERE id = ?", cid)[0]
    assert conv["outcome"] == "safety_stop" and conv["ended_at"]
    t = rows(started, "SELECT * FROM turns WHERE conversation_id = ?", cid)[0]
    assert t["safety_verdict"] == "emergency" and t["offered"] == "{}"
    assert t["reply_text"] == reply["text"]
    ((tx, record),) = calls.handoffs
    assert tx is not None
    assert record.kind == "safety_stop" and record.conversation_id == cid
    assert record.intent == "safety" and record.told_caller == reply["text"]
    again = client.post(f"/conversations/{cid}/messages", json={"text": "hello?"})
    assert again.status_code == 409 and again.json()["error"] == "conversation_ended"
    assert len(model.received) == 1


def test_nothing_is_written_before_the_screen_says_safe(
    started: Settings, calls: Calls
):
    clock = FakeClock()
    gate = threading.Event()
    calls.screen_gate = gate
    calls.screen_after = lambda: clock.advance(2)
    calls.verdicts = ["burning_followup", "safe"]

    class Model(FakeModelProvider):
        def complete(self, messages, *, tools=None, timeout_s):
            out = super().complete(messages, tools=tools, timeout_s=timeout_s)
            gate.set()
            return out

    model = Model(
        results=[
            result(assistant(calls=[windows_call()])),
            result(assistant("Tuesday 8-10 is open.")),
            book_call(56, "There's a burning smell"),
        ]
    )
    client = client_for(started, model, clock)
    cid = new_conversation(client)
    match(started, cid)
    calls.verdicts = ["safe", "burning_followup", "safe"]
    say(client, cid, "I need a visit")
    calls.windows.clear()
    gate.clear()
    reply = say(client, cid, "There's a burning smell")
    assert calls.books == [] and calls.windows == []
    assert reply["text"] == guards.BURNING_FOLLOWUP_TEXT
    assert reply["choices"] == [] and reply["booking"] is None
    assert reply["banner"] == "none" and reply["status"] == "active"
    t = rows(started, "SELECT * FROM turns WHERE conversation_id = ? AND seq = 2", cid)[
        0
    ]
    assert t["safety_verdict"] == "burning_followup" and t["latency_ms"] >= 2000
    assert json.loads(t["model_messages"]) == [
        {"role": "user", "content": "There's a burning smell"},
        {"role": "assistant", "content": guards.BURNING_FOLLOWUP_TEXT},
    ]
    assert rows(started, "SELECT outcome FROM conversations")[0][0] is None
    say(client, cid, "No, nothing else")
    assert calls.screens[-1] == ("No, nothing else", True)


def test_a_matched_caller_hears_about_their_account(started: Settings, calls: Calls):
    calls.verdicts = ["emergency"]
    client = client_for(started, FakeModelProvider())
    cid = new_conversation(client)
    match(started, cid, "MHC-10001")
    reply = say(client, cid, "I smell gas")
    assert reply["text"].endswith(
        "Your account has been flagged for a safety follow-up."
    )
    assert calls.handoffs[0][1].customer_id == "MHC-10001"


@pytest.mark.parametrize("verdict", ["emergency", "burning_followup"])
def test_vr2_no_write_or_offer_unless_safe(
    started: Settings, calls: Calls, verdict: str
):
    calls.verdicts = ["safe", verdict]
    model = FakeModelProvider(
        results=[
            result(assistant(calls=[windows_call()])),
            result(assistant("Tuesday 8-10 is open.")),
            result(
                assistant(
                    calls=[
                        windows_call("w2"),
                        tool_call(
                            "b",
                            "book_visit",
                            slotId=56,
                            issue="no heat",
                            callerQuote="yes",
                        ),
                    ]
                )
            ),
        ]
    )
    client = client_for(started, model)
    cid = new_conversation(client)
    match(started, cid)
    say(client, cid, "I need a visit")
    before = len(calls.windows)
    reply = say(client, cid, "yes")
    assert calls.books == [] and len(calls.windows) == before
    assert reply["choices"] == [] and reply["booking"] is None
    t = rows(started, "SELECT * FROM turns WHERE seq = 2")[0]
    assert t["offered"] == "{}" and t["has_write"] == 0


def test_a_write_needs_the_callers_own_words(started: Settings, calls: Calls):
    client, cid, model = offer_turn(
        started,
        calls,
        [book_call(56, "yes book it"), result(assistant("I could not book that."))],
    )
    first = rows(started, "SELECT offered FROM turns WHERE seq = 1")[0][0]
    assert json.loads(first) == {"slotIds": [56], "appointmentIds": []}
    reply = say(client, cid, "hmm, maybe")
    assert calls.books == [] and reply["booking"] is None
    out = last_tool_result(model)
    assert out["ok"] is False and out["error"] == "caller_quote_not_in_message"
    t = rows(started, "SELECT tools_called FROM turns WHERE seq = 2")[0][0]
    assert json.loads(t)[0]["ok"] is False


def test_a_write_needs_a_window_that_was_offered(started: Settings, calls: Calls):
    client, cid, model = offer_turn(
        started, calls, [book_call(99, "yes"), result(assistant("No."))]
    )
    say(client, cid, "yes")
    assert calls.books == []
    assert last_tool_result(model)["error"] == "target_not_offered"


def test_a_window_offered_in_this_turn_is_not_enough(started: Settings, calls: Calls):
    model = FakeModelProvider(
        results=[
            result(assistant(calls=[windows_call()])),
            book_call(56, "yes"),
            result(assistant("No.")),
        ]
    )
    client = client_for(started, model)
    cid = new_conversation(client)
    match(started, cid)
    say(client, cid, "yes")
    assert calls.books == []


def test_az2_write_refusal_rules():
    refuse = guards.write_refusal
    ok = {"callerQuote": "yes please"}
    assert refuse("book_visit", {"slotId": 56}, "yes please", {56}, set()) == (
        "caller_quote_not_in_message"
    )
    for quote in (None, "", "  ", "Yes please", "yes  please"):
        args = {"slotId": 56, "callerQuote": quote}
        assert refuse("book_visit", args, "yes please", {56}, set()) == (
            "caller_quote_not_in_message"
        )
    for slot in (99, "56", None, True, 56.0):
        args = {**ok, "slotId": slot}
        assert refuse("book_visit", args, "yes please", {56}, set()) == (
            "target_not_offered"
        )
    move = {**ok, "appointmentId": 3, "newSlotId": 56}
    assert refuse("move_visit", move, "yes please", {56}, {3}) is None
    assert refuse("move_visit", move, "yes please", {56}, set()) == "target_not_offered"
    assert refuse("move_visit", move, "yes please", set(), {3}) == "target_not_offered"
    cancel = {**ok, "appointmentId": 3}
    assert refuse("cancel_visit", cancel, "yes please", set(), {3}) is None
    assert refuse("cancel_visit", cancel, "yes please", {3}, set()) == (
        "target_not_offered"
    )
    assert (
        refuse("book_visit", {**ok, "slotId": 56}, "ok yes please", {56}, set()) is None
    )


def test_a_card_only_from_a_committed_write(started: Settings, calls: Calls):
    calls.book_error = scheduling.SlotUnavailable("taken")
    client, cid, model = offer_turn(
        started,
        calls,
        [book_call(56, "yes book it"), result(assistant("Sorry, that is gone."))],
    )
    reply = say(client, cid, "yes book it")
    assert reply["booking"] is None and "request_callback" in reply["actions"]
    out = last_tool_result(model)
    assert out["ok"] is False and "SlotUnavailable" in out["error"]
    assert out["instruction"] == guards.FAILED_WRITE_INSTRUCTION
    assert rows(started, "SELECT has_write FROM turns WHERE seq = 2")[0][0] == 0


def test_a_committed_booking_survives_a_failed_turn(started: Settings, calls: Calls):
    class FailsAfterBooking(FakeModelProvider):
        def complete(self, messages, *, tools=None, timeout_s):
            if self.results is not None and len(self.results) == 1:
                raise RuntimeError("provider down")
            return super().complete(messages, tools=tools, timeout_s=timeout_s)

    model = FailsAfterBooking(
        results=[
            result(assistant(calls=[windows_call()])),
            result(assistant("Tuesday 8-10 is open.")),
            book_call(56, "yes book it"),
            result(assistant("never reached")),
        ]
    )
    client = client_for(started, model)
    cid = new_conversation(client)
    match(started, cid)
    say(client, cid, "I need a visit")
    reply = say(client, cid, "yes book it")
    assert reply["booking"] == json.loads(BOOKING.model_dump_json(by_alias=True))
    assert reply["text"] == guards.confirmation_text(BOOKING)
    assert reply["banner"] == "none"
    t = rows(started, "SELECT * FROM turns WHERE seq = 2")[0]
    assert t["has_write"] == 1 and t["error"] == "provider_error"
    stored = json.loads(t["model_messages"])
    assert stored[-1] == {"role": "assistant", "content": reply["text"]}
    assert stored[-2]["role"] == "tool"


def test_a_conversation_closed_during_the_model_call_gets_no_turn(
    started: Settings, calls: Calls
):
    for verdict in ("safe", "emergency"):
        calls.verdicts = [verdict]
        calls.handoffs.clear()

        class Model(FakeModelProvider):
            def complete(self, messages, *, tools=None, timeout_s):
                conn = sqlite3.connect(started.APP_DB_PATH)
                conn.execute(
                    "UPDATE conversations SET outcome = 'failed', "
                    "ended_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')"
                )
                conn.commit()
                conn.close()
                return super().complete(messages, tools=tools, timeout_s=timeout_s)

        client = client_for(started, Model(results=[result(assistant("Hello."))]))
        cid = new_conversation(client)
        resp = client.post(f"/conversations/{cid}/messages", json={"text": "hi"})
        assert resp.status_code == 409 and resp.json()["error"] == "conversation_ended"
        assert rows(started, "SELECT * FROM turns WHERE conversation_id = ?", cid) == []
        conv = rows(started, "SELECT * FROM conversations WHERE id = ?", cid)[0]
        assert conv["turn_count"] == 0 and conv["outcome"] == "failed"
        assert calls.handoffs == []
        started_db = sqlite3.connect(started.APP_DB_PATH)
        started_db.execute("DELETE FROM conversations")
        started_db.commit()
        started_db.close()


def test_the_quote_must_be_a_whole_phrase_of_the_message():
    refuse = guards.write_refusal
    text = "yes please, the Tuesday one"
    for quote in ("y", "ye", "es", "plea", "Tues", "a", " y "):
        args = {"slotId": 56, "callerQuote": quote}
        assert refuse("book_visit", args, text, {56}, set()) == (
            "caller_quote_not_in_message"
        )
    for quote in ("yes", "yes please", "the Tuesday one", "Tuesday"):
        args = {"slotId": 56, "callerQuote": quote}
        assert refuse("book_visit", args, text, {56}, set()) is None
    assert (
        refuse("book_visit", {"slotId": 56, "callerQuote": "ok"}, "ok.", {56}, set())
        is None
    )
