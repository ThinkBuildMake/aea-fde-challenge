"""S33: identify the caller and book a visit through the real Conversation, Scheduling and
Knowledge modules on a seed copy. Only the network edges are scripted: the recorded model,
the hashing embedder and the conftest danger screen."""

import json
import sqlite3
import threading
from contextlib import closing
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.conversation import guards
from app.knowledge.embeddings import FakeEmbedder
from app.knowledge.service import rebuild_index
from app.llm import FakeModelProvider, ModelResult
from app.main import create_app
from app.scheduling.store import zone_for_city
from app.settings import Settings
from tests.gate.bookings import orphans
from tests.gate.harness import FakeClock, evaluate_pf2
from tests.test_turn import assistant, result, tool_call

CHIP = "My AC is blowing warm air"
VISIT_TYPE = (
    "I'll book an HVAC repair visit for you. May I have your name and one of your "
    "phone number, account number or service address?"
)
OMAR = "Omar Patel, account MHC-10002"
DANIEL = "Daniel Reyes, 512-555-0104"
MARIA = "Maria Johnson, 512-292-7955"
OMAR_FIRST = "Wednesday October 21, 8 AM to 12 PM, Jun Park"
EARLIER = "Nothing earlier? Ask for an earlier window"
CONFIRMATION = (
    "Your HVAC repair visit is booked for Wednesday October 21, 8 AM to 12 PM with "
    "Jun Park. There is an $89 diagnostic fee, credited toward the repair."
)


def identify_calls(who: str) -> list[dict[str, Any]]:
    name, detail = who.split(", ")
    if detail.startswith("account "):
        args = {"name": name, "accountNumber": detail.removeprefix("account ")}
    else:
        args = {"name": name, "phone": detail}
    identify = tool_call("id", "identify_customer")
    identify["function"]["arguments"] = json.dumps(
        args
    )  # tool_call's own `name` clashes
    return [identify, tool_call("w", "find_open_windows", serviceType="hvac_repair")]


def up_to_windows(who: str) -> list[ModelResult]:
    """The recorded turns: chip → safety question, No → visit type, identity → windows."""
    return [
        result(assistant(guards.BURNING_FOLLOWUP_TEXT)),
        result(assistant(VISIT_TYPE)),
        result(assistant(calls=identify_calls(who))),
        result(
            assistant(f"Thank you, {who.split()[0]}. Pick a window that suits you:")
        ),
    ]


def pick(
    slot_id: int, label: str, confirmation: str = CONFIRMATION
) -> list[ModelResult]:
    return [
        result(
            assistant(
                calls=[
                    tool_call(
                        "b",
                        "book_visit",
                        slotId=slot_id,
                        issue="AC blowing warm air",
                        callerQuote=label,
                    )
                ]
            )
        ),
        result(assistant(confirmation)),
    ]


class Booker:
    """An app on the seed copy with a recorded model; its index is built for get_fee."""

    def __init__(self, settings: Settings, model: Any) -> None:
        self.settings = settings
        self.model = model
        self.clock = FakeClock()
        app = create_app(
            settings, model=model, clock=self.clock, embedder=FakeEmbedder()
        )
        rebuild_index(app.state.ctx)
        self.client = TestClient(app)
        self.cid = self.client.post("/conversations").json()["conversationId"]

    def say(self, text: str) -> dict[str, Any]:
        response = self.client.post(
            f"/conversations/{self.cid}/messages", json={"text": text}
        )
        assert response.status_code == 200
        reply = response.json()
        print(f"\nCALLER: {text}\nAGENT: {reply['text']}")
        print(f"choices={[c['label'] for c in reply['choices']]}")
        print(
            f"booking={reply['booking']} banner={reply['banner']} actions={reply['actions']}"
        )
        return reply

    def identify(self, who: str) -> dict[str, Any]:
        self.say(CHIP)
        self.say("No")
        return self.say(who)

    def turns(self, column: str) -> list[Any]:
        return [
            r[0]
            for r in app_rows(
                self.settings,
                f"SELECT {column} FROM turns WHERE conversation_id = ? ORDER BY seq",
                self.cid,
            )
        ]


def app_rows(settings: Settings, sql: str, *args: Any) -> list[tuple[Any, ...]]:
    with closing(sqlite3.connect(settings.APP_DB_PATH)) as conn:
        return conn.execute(sql, args).fetchall()


def schedule_rows(settings: Settings, sql: str, *args: Any) -> list[tuple[Any, ...]]:
    with closing(sqlite3.connect(settings.SCHEDULING_DB_PATH)) as conn:
        return conn.execute(sql, args).fetchall()


def snapshot(settings: Settings) -> dict[str, Any]:
    return {
        "slots": {
            r[0]: r[1:]
            for r in schedule_rows(
                settings,
                "SELECT slot_id, status, zone, slot_date, service_type FROM appointment_slots",
            )
        },
        "appointments": {
            r[0]
            for r in schedule_rows(settings, "SELECT appointment_id FROM appointments")
        },
    }


def new_appointments(
    settings: Settings, before: dict[str, Any]
) -> list[tuple[Any, ...]]:
    return [
        r
        for r in schedule_rows(
            settings,
            "SELECT appointment_id, slot_id, customer_id, status FROM appointments "
            "ORDER BY appointment_id",
        )
        if r[0] not in before["appointments"]
    ]


def assert_slot_rules(settings: Settings, before: dict[str, Any]) -> None:
    """VR-7: no new appointment on a slot that was blocked or booked, member-only for a
    non-member, outside the customer's zone or outside 2026-10-16..2026-11-05."""
    for _, slot_id, customer_id, _ in new_appointments(settings, before):
        status, zone, day, _ = before["slots"][slot_id]
        city, tier = schedule_rows(
            settings,
            "SELECT city, membership_tier FROM customers WHERE customer_id = ?",
            customer_id,
        )[0]
        assert status in ("open", "reserved_members")
        assert status == "open" or tier in ("standard", "plus")
        assert zone == zone_for_city(city)
        assert "2026-10-16" <= day <= "2026-11-05"
    with closing(sqlite3.connect(settings.SCHEDULING_DB_PATH)) as conn:
        assert orphans(conn) == (0, 0)


def labels(reply: dict[str, Any]) -> list[str]:
    return [c["label"] for c in reply["choices"]]


def test_omar_gets_his_zones_windows(kb_settings: Settings):
    booker = Booker(kb_settings, FakeModelProvider(results=up_to_windows(OMAR)))
    shown = booker.identify(OMAR)
    offered = json.loads(booker.turns("offered")[-1])["slotIds"]
    print(f"offered slotIds={offered}")
    assert labels(shown) == [
        OMAR_FIRST,
        "Wednesday October 21, 1 PM to 5 PM, Jun Park",
        "Friday October 23, 12 PM to 4 PM, Jun Park",
        EARLIER,
    ]
    assert offered == [115, 119, 185]


def test_clicking_the_first_window_books_slot_115(kb_settings: Settings):
    before = snapshot(kb_settings)
    booker = Booker(
        kb_settings,
        FakeModelProvider(results=[*up_to_windows(OMAR), *pick(115, OMAR_FIRST)]),
    )
    shown = booker.identify(OMAR)
    reply = booker.say(shown["choices"][0]["text"])
    print(f"slot 115 seed status={before['slots'][115][0]}")
    assert reply["booking"] == {
        "appointmentId": reply["booking"]["appointmentId"],
        "slotId": 115,
        "date": "2026-10-21",
        "window": "08:00-12:00",
        "technicianName": "Jun Park",
        "serviceType": "hvac_repair",
        "zone": "south",
        "diagnosticFeeCents": 8900,
        "diagnosticFeeWaived": False,
    }
    assert reply["text"] == CONFIRMATION
    assert booker.turns("error")[-1] is None
    changed = {
        slot_id: row[0]
        for slot_id, row in snapshot(kb_settings)["slots"].items()
        if row != before["slots"][slot_id]
    }
    added = new_appointments(kb_settings, before)
    changes = app_rows(
        kb_settings,
        "SELECT action, appointment_id, slot_id, customer_id, confirmed_date, "
        "confirmed_window, confirmed_technician FROM visit_changes",
    )
    print(f"changed slots={changed}\nnew appointments={added}\nvisit_changes={changes}")
    assert changed == {115: "booked"}
    appointment_id = reply["booking"]["appointmentId"]
    assert added == [(appointment_id, 115, "MHC-10002", "scheduled")]
    assert changes == [
        (
            "book",
            appointment_id,
            115,
            "MHC-10002",
            "2026-10-21",
            "08:00-12:00",
            "Jun Park",
        )
    ]
    assert_slot_rules(kb_settings, before)


def test_member_only_windows_stay_hidden(kb_settings: Settings):
    before = snapshot(kb_settings)
    booker = Booker(
        kb_settings,
        FakeModelProvider(
            results=[*up_to_windows(DANIEL), *pick(1, DANIEL, "Booked.")]
        ),
    )
    shown = booker.identify(DANIEL)
    offered = json.loads(booker.turns("offered")[-1])["slotIds"]
    print(f"offered slotIds={offered}; slot 1 seed status={before['slots'][1][0]}")
    assert labels(shown)[0] == "Monday October 19, 8 AM to 12 PM, Marta Kowalski"
    assert offered[0] == 56 and 1 not in offered
    refused = booker.say(DANIEL)
    errors = [t["error"] for t in json.loads(booker.turns("tools_called")[-1])]
    print(f"book_visit on slot 1: {errors}")
    assert errors == ["target_not_offered"]
    assert refused["booking"] is None
    assert new_appointments(kb_settings, before) == []
    assert_slot_rules(kb_settings, before)


def test_a_day_with_no_window_gets_the_nearest(kb_settings: Settings):
    nearest = [
        result(
            assistant(
                calls=[
                    tool_call(
                        "s",
                        "find_open_windows",
                        serviceType="hvac_repair",
                        preferredDate="2026-10-18",
                    )
                ]
            )
        ),
        result(
            assistant(
                "There is no window that day. The nearest is Monday October 19, "
                "8 AM to 12 PM with Marta Kowalski."
            )
        ),
    ]
    booker = Booker(
        kb_settings, FakeModelProvider(results=[*up_to_windows(DANIEL), *nearest])
    )
    booker.identify(DANIEL)
    reply = booker.say("Can someone come on Sunday 2026-10-18?")
    told = next(
        json.loads(m["content"])
        for m in json.loads(booker.turns("model_messages")[-1])
        if m["role"] == "tool"
    )
    print(
        f"matchedRequest={told['matchedRequest']} first={told['windows'][0]['slotId']}"
    )
    assert told["matchedRequest"] is False
    assert labels(reply)[0] == "Monday October 19, 8 AM to 12 PM, Marta Kowalski"


class Racer:
    """A recorded caller who answers from the last message, so two can run at once.
    Both wait at the barrier before asking to book, so their writes collide."""

    def __init__(self, who: str, barrier: threading.Barrier) -> None:
        self.who = who
        self.barrier = barrier

    def complete(self, messages: list[dict[str, Any]], **_: Any) -> ModelResult:
        last = messages[-1]
        if last["role"] == "user":
            text = last["content"]
            if text == OMAR_FIRST:
                self.barrier.wait(timeout=10)
                return pick(115, text)[0]
            replies = {
                CHIP: up_to_windows(self.who)[0],
                "No": up_to_windows(self.who)[1],
            }
            return replies.get(text) or up_to_windows(self.who)[2]
        names = {
            c["id"]: c["function"]["name"]
            for m in messages
            for c in m.get("tool_calls") or []
        }
        this_turn = messages[
            max(i for i, m in enumerate(messages) if m["role"] == "user") :
        ]
        outcomes = [
            (names[m["tool_call_id"]], json.loads(m["content"]))
            for m in this_turn
            if m["role"] == "tool"
        ]
        name, out = outcomes[-1]
        if name == "book_visit":
            if out.get("ok"):
                return result(assistant(CONFIRMATION))
            return result(
                assistant(
                    calls=[
                        tool_call("w2", "find_open_windows", serviceType="hvac_repair")
                    ]
                )
            )
        if any(n == "book_visit" for n, _ in outcomes):
            return result(
                assistant(
                    "Sorry, that window was just taken and is not booked. Here are others:"
                )
            )
        return up_to_windows(self.who)[3]


def test_two_callers_racing_for_slot_115_write_one(kb_settings: Settings):
    before = snapshot(kb_settings)
    barrier = threading.Barrier(2)
    omar = Booker(kb_settings, Racer(OMAR, barrier))
    maria = Booker(kb_settings, Racer(MARIA, barrier))
    for booker, who in ((omar, OMAR), (maria, MARIA)):
        assert labels(booker.identify(who))[0] == OMAR_FIRST
    replies: dict[str, dict[str, Any]] = {}
    threads = [
        threading.Thread(
            target=lambda b=b, k=k: replies.__setitem__(k, b.say(OMAR_FIRST))
        )
        for b, k in ((omar, "omar"), (maria, "maria"))
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    on_115 = schedule_rows(
        kb_settings,
        "SELECT customer_id FROM appointments WHERE slot_id = 115 AND status = 'scheduled'",
    )
    print(f"appointments on slot 115={on_115}")
    assert len(on_115) == 1
    winner = "omar" if on_115[0][0] == "MHC-10002" else "maria"
    loser = replies["maria" if winner == "omar" else "omar"]
    assert replies[winner]["booking"]["slotId"] == 115
    assert loser["booking"] is None
    assert "request_callback" in loser["actions"]
    assert labels(loser)[0] == "Wednesday October 21, 1 PM to 5 PM, Jun Park"
    assert OMAR_FIRST not in labels(loser)
    assert "booked for" not in loser["text"] and "confirmed" not in loser["text"]
    print(f"winner={winner}; the other was offered {labels(loser)}")
    assert_slot_rules(kb_settings, before)


def test_unwritable_schedule_never_confirms(
    kb_settings: Settings, monkeypatch: pytest.MonkeyPatch
):
    before = snapshot(kb_settings)
    model = FakeModelProvider(results=[*up_to_windows(OMAR), *pick(115, OMAR_FIRST)])
    booker = Booker(kb_settings, model)
    booker.identify(OMAR)
    model.delay_s, model.sleep = 2.0, booker.clock.advance

    def read_only(path: Any) -> sqlite3.Connection:
        # The container runs as root, so chmod cannot make the file unwritable.
        conn = sqlite3.connect(
            f"file:{path}?mode=ro", uri=True, timeout=5, check_same_thread=False
        )
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr("app.scheduling.store.connect_scheduling_db", read_only)
    reply = booker.say(OMAR_FIRST)
    print(f"latencyMs={reply['turn']['latencyMs']} error={booker.turns('error')[-1]}")
    assert reply["booking"] is None
    assert reply["text"] == guards.FALLBACK_TEXT
    assert reply["banner"] == "error"
    assert reply["actions"] == ["request_callback"]
    assert reply["turn"]["latencyMs"] <= 10000
    assert snapshot(kb_settings) == before
    assert app_rows(kb_settings, "SELECT COUNT(*) FROM visit_changes") == [(0,)]


def test_wrong_confirmation_is_replaced_by_the_row(kb_settings: Settings):
    wrong = "You are booked for Thursday October 22, 1 PM to 5 PM with Ray Mendoza."
    booker = Booker(
        kb_settings,
        FakeModelProvider(
            results=[*up_to_windows(OMAR), *pick(115, OMAR_FIRST, wrong)]
        ),
    )
    booker.identify(OMAR)
    reply = booker.say(OMAR_FIRST)
    print(f"reply text={reply['text']!r} error={booker.turns('error')[-1]}")
    assert reply["text"] == "You are booked for 2026-10-21, 08:00-12:00, with Jun Park."
    assert booker.turns("error")[-1] == "confirmation_mismatch"
    assert reply["booking"]["technicianName"] == "Jun Park"


@pytest.mark.parametrize(
    "slot_id",
    [7, 195, 1, 56],
    ids=["booked", "blocked", "member_only", "other_zone"],
)
def test_no_booking_breaks_the_slot_rules(kb_settings: Settings, slot_id: int):
    before = snapshot(kb_settings)
    booker = Booker(
        kb_settings,
        FakeModelProvider(
            results=[*up_to_windows(OMAR), *pick(slot_id, OMAR_FIRST, "ok")]
        ),
    )
    booker.identify(OMAR)
    reply = booker.say(OMAR_FIRST)
    errors = [t["error"] for t in json.loads(booker.turns("tools_called")[-1])]
    print(
        f"slot {slot_id} ({before['slots'][slot_id][0]}, {before['slots'][slot_id][1]}): {errors}"
    )
    assert errors == ["target_not_offered"]
    assert reply["booking"] is None
    assert new_appointments(kb_settings, before) == []
    assert_slot_rules(kb_settings, before)


@pytest.mark.parametrize(
    ("delay_s", "latency_ms", "passed"), [(2.0, 4000, True), (6.0, 12000, False)]
)
def test_booking_turn_within_pf2(
    kb_settings: Settings, delay_s: float, latency_ms: int, passed: bool
):
    model = FakeModelProvider(results=[*up_to_windows(OMAR), *pick(115, OMAR_FIRST)])
    booker = Booker(kb_settings, model)
    booker.identify(OMAR)
    model.delay_s, model.sleep = delay_s, booker.clock.advance
    reply = booker.say(OMAR_FIRST)
    verdict = evaluate_pf2([reply["turn"]["latencyMs"]])
    print(verdict.message)
    assert reply["booking"]["slotId"] == 115
    assert reply["turn"]["latencyMs"] == latency_ms
    assert verdict.passed is passed


@pytest.mark.parametrize("answer", ["Yes", "Not sure"])
@pytest.mark.parametrize(
    "question",
    [
        guards.BURNING_FOLLOWUP_TEXT,
        f"I'm sorry your AC is acting up. {guards.BURNING_QUESTION}",
    ],
    ids=["exact", "own_apology"],
)
def test_an_unclear_answer_to_the_agents_safety_question_stops(
    kb_settings: Settings, answer: str, question: str
):
    before = snapshot(kb_settings)
    model = FakeModelProvider(
        results=[result(assistant(question)), *up_to_windows(OMAR)[1:]]
    )
    booker = Booker(kb_settings, model)
    assert booker.say(CHIP)["text"] == question
    reply = booker.say(answer)
    verdicts = booker.turns("safety_verdict")
    print(
        f"{answer!r}: status={reply['status']} banner={reply['banner']} verdicts={verdicts}"
    )
    assert reply["status"] == "safety_stop"
    assert reply["banner"] == "safety_stop"
    assert reply["text"] == guards.emergency_text(False)
    assert reply["choices"] == [] and reply["booking"] is None
    assert verdicts == ["safe", "emergency"]
    assert new_appointments(kb_settings, before) == []
    assert snapshot(kb_settings) == before
