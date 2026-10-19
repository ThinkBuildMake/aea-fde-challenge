"""Opt-in: S33's booking conversations against the real agent model, embedder and danger screen.

Needs MERIDIAN_LIVE_TESTS=1 and OPENROUTER_API_KEY; about $0.05 for the module.
Every booking lands in a temp copy of the scheduling database.
"""

import json
import os
import re
import sqlite3
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.knowledge.service import rebuild_index
from app.llm import OpenRouterProvider
from app.main import create_app
from app.settings import Settings

pytestmark = pytest.mark.skipif(
    os.environ.get("MERIDIAN_LIVE_TESTS") != "1"
    or not os.environ.get("OPENROUTER_API_KEY"),
    reason="live tests need MERIDIAN_LIVE_TESTS=1 and OPENROUTER_API_KEY",
)

CHIP = "My AC is blowing warm air"
EARLIER = "Nothing earlier? Ask for an earlier window"
OMAR_FIRST = "Wednesday October 21, 8 AM to 12 PM, Jun Park"
DANIEL_FIRST = "Monday October 19, 8 AM to 12 PM, Marta Kowalski"


@pytest.fixture(autouse=True)
def screen_says_safe():
    """Overrides the conftest stub: this module runs the real danger screen."""


@pytest.fixture
def live(kb_settings: Settings):
    settings = kb_settings.model_copy(
        update={"OPENROUTER_API_KEY": SecretStr(os.environ["OPENROUTER_API_KEY"])}
    )
    provider = OpenRouterProvider(settings)
    app = create_app(settings, model=provider)
    rebuild_index(app.state.ctx)
    with TestClient(app) as client:
        yield Chat(client, settings)
    provider.client.close()


class Chat:
    def __init__(self, client: TestClient, settings: Settings) -> None:
        self.client = client
        self.settings = settings
        self.cid = ""

    def start(self) -> None:
        self.cid = self.client.post("/conversations").json()["conversationId"]

    def say(self, text: str) -> dict[str, Any]:
        response = self.client.post(
            f"/conversations/{self.cid}/messages", json={"text": text}
        )
        assert response.status_code == 200
        reply = response.json()
        print(f"\nCALLER: {text}\nAGENT: {reply['text']}")
        print(f"choices={[c['label'] for c in reply['choices']]}")
        print(f"booking={reply['booking']} actions={reply['actions']}")
        print(f"tools so far={self.tools()}")
        return reply

    def tools(self) -> list[str]:
        """Tool names called so far in this conversation."""
        return [
            t["name"]
            for r in self.app_db(
                "SELECT tools_called FROM turns WHERE conversation_id = ? ORDER BY seq",
                self.cid,
            )
            for t in json.loads(r[0])
        ]

    def offered(self) -> list[int]:
        return [
            i
            for r in self.app_db(
                "SELECT offered FROM turns WHERE conversation_id = ?", self.cid
            )
            for i in json.loads(r[0] or "{}").get("slotIds", [])
        ]

    def app_db(self, sql: str, *args: Any) -> list[tuple[Any, ...]]:
        return _query(str(self.settings.APP_DB_PATH), sql, args)

    def schedule(self, sql: str, *args: Any) -> list[tuple[Any, ...]]:
        return _query(str(self.settings.SCHEDULING_DB_PATH), sql, args)

    def identify(self, who: str) -> dict[str, Any]:
        """The chip, the safety answer, then the caller's name and detail."""
        self.start()
        self.say(CHIP)
        self.say("No")
        return self.say(who)


def _query(path: str, sql: str, args: tuple[Any, ...]) -> list[tuple[Any, ...]]:
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def has(text: str, pattern: str) -> bool:
    return re.search(pattern, text, re.IGNORECASE) is not None


def test_visit_type_named_after_the_safety_question(live: Chat):
    live.start()
    first = live.say(CHIP)
    assert has(first["text"], r"smoke|spark|breaker")
    second = live.say("No")
    text = second["text"]
    assert has(text, r"HVAC repair")
    assert has(text, r"name")
    assert has(text, r"phone|account|address")
    assert "identify_customer" not in live.tools()


def test_omar_books_the_first_window(live: Chat):
    appointments_before = live.schedule("SELECT COUNT(*) FROM appointments")[0][0]
    shown = live.identify("Omar Patel, account MHC-10002")
    labels = [c["label"] for c in shown["choices"]]
    assert labels[0] == OMAR_FIRST
    assert labels[-1] == EARLIER
    booked = live.say(shown["choices"][0]["text"])["booking"]
    assert booked is not None
    assert (
        booked["slotId"],
        booked["date"],
        booked["window"],
        booked["technicianName"],
        booked["diagnosticFeeCents"],
        booked["diagnosticFeeWaived"],
    ) == (115, "2026-10-21", "08:00-12:00", "Jun Park", 8900, False)
    status = live.schedule("SELECT status FROM appointment_slots WHERE slot_id = 115")
    new = live.schedule(
        "SELECT slot_id, customer_id FROM appointments WHERE customer_id = ? "
        "AND slot_id = 115",
        "MHC-10002",
    )
    count = live.schedule("SELECT COUNT(*) FROM appointments")[0][0]
    print(
        f"slot 115={status} new appointments={new} total {appointments_before}->{count}"
    )
    assert status == [("booked",)]
    assert new == [(115, "MHC-10002")]
    assert count == appointments_before + 1


def test_daniel_sees_no_member_windows(live: Chat):
    shown = live.identify("Daniel Reyes, 512-555-0104")
    assert shown["choices"][0]["label"] == DANIEL_FIRST
    assert 1 not in live.offered()


def test_sunday_gets_the_nearest_windows(live: Chat):
    live.identify("Daniel Reyes, 512-555-0104")
    reply = live.say("Can someone come on Sunday 2026-10-18?")
    text = reply["text"]
    assert has(
        text, r"\bno\b.{0,40}(window|appointment|availab|opening)|nothing|not available"
    )
    assert has(text, r"Monday,? October 19")
    assert has(text, r"8 ?AM|8:00")
    assert reply["choices"][0]["label"] == DANIEL_FIRST


def test_outside_the_service_area(live: Chat):
    before = live.schedule("SELECT COUNT(*) FROM appointments")[0][0]
    live.start()
    reply = live.say("I'm in San Antonio and my AC is out")
    text = reply["text"]
    assert "San Antonio" in text
    assert has(text, r"outside")
    assert has(text, r"service area")
    assert has(text, r"local|another provider|cannot send|can't send|not able to send")
    assert reply["booking"] is None
    called = live.tools()
    assert "identify_customer" not in called and "book_visit" not in called
    assert live.schedule("SELECT COUNT(*) FROM appointments")[0][0] == before
