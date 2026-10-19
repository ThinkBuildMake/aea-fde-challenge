"""S31 gate: the safety seams through the real Safety, Conversation, Follow-ups and Scheduling modules.

Only the network edges are scripted: the safety classifier's reply (the verdicts the
real screen model gave on 2026-10-19), the embedder and the agent model (a recording
that tries to identify a real customer and book a window whatever the caller said).
VR-2: the seed copy of the scheduling database is identical before and after each case.
"""

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.conversation import guards
from app.knowledge.embeddings import FakeEmbedder
from app.knowledge.service import rebuild_index
from app.llm import FakeModelProvider, ModelResult
from app.main import create_app
from app.safety.service import OpenRouterSafetyClassifier
from app.settings import Settings
from tests.gate.harness import FakeClock

RECORDING = json.loads(
    (Path(__file__).parent / "recorded" / "smell_gas.json").read_text()
)
GAS = "I smell gas"
BURNING = "There's a burning smell coming from my furnace"
YES = "Yes, the breaker tripped"
NO = "No, nothing like that"
# What the real screen model answered for each message on 2026-10-19.
SCREEN = {
    GAS: {"verdict": "emergency", "reason": "gas"},
    BURNING: {"verdict": "burning_followup", "reason": "burning_smell"},
    YES: {"verdict": "burning_followup", "reason": "burning_smell"},
    NO: {"verdict": "burning_followup", "reason": "burning_smell"},
}


def recorded(*parts: str) -> list[ModelResult]:
    return [
        ModelResult(
            dict(e["message"]),
            prompt_tokens=e["prompt_tokens"],
            completion_tokens=e["completion_tokens"],
            cost_usd=e["cost"],
        )
        for part in parts
        for e in RECORDING[part]
    ]


@pytest.fixture
def screen(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    """The classifier answers as recorded; append True to make it fail."""
    failing: list[bool] = []

    def classify(self, messages, timeout_s):
        if failing:
            raise RuntimeError("screen down")
        message = json.loads(messages[-1]["content"])["message"]
        return json.dumps(SCREEN[message])

    monkeypatch.setattr(OpenRouterSafetyClassifier, "classify", classify)
    return failing


class Chat:
    def __init__(self, settings: Settings, model: FakeModelProvider) -> None:
        self.settings = settings
        app = create_app(
            settings, model=model, clock=FakeClock(), embedder=FakeEmbedder()
        )
        rebuild_index(app.state.ctx)  # so a booking that slipped through could price
        self.client = TestClient(app)
        self.cid = self.client.post("/conversations").json()["conversationId"]

    def post(self, text: str):
        return self.client.post(
            f"/conversations/{self.cid}/messages", json={"text": text}
        )

    def say(self, text: str) -> dict[str, Any]:
        response = self.post(text)
        assert response.status_code == 200
        reply = response.json()
        print(f"\nCALLER: {text}\nAGENT: {reply['text']}")
        print(
            f"status={reply['status']} banner={reply['banner']} "
            f"choices={reply['choices']} booking={reply['booking']} "
            f"actions={reply['actions']}"
        )
        return reply

    def app_db(self, sql: str, *args: Any) -> list[sqlite3.Row]:
        conn = sqlite3.connect(self.settings.APP_DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            return conn.execute(sql, args).fetchall()
        finally:
            conn.close()

    def turns(self) -> list[sqlite3.Row]:
        found = self.app_db(
            "SELECT seq, safety_verdict, tools_called, has_write, offered FROM turns "
            "WHERE conversation_id = ? ORDER BY seq",
            self.cid,
        )
        for t in found:
            print(
                f"turn {t['seq']}: safety_verdict={t['safety_verdict']} "
                f"tools_called={t['tools_called']} has_write={t['has_write']} "
                f"offered={t['offered']}"
            )
        return found

    def handoffs(self) -> list[tuple[str, str]]:
        found = [
            (r["kind"], r["reason"])
            for r in self.app_db(
                "SELECT kind, reason FROM handoffs WHERE conversation_id = ?", self.cid
            )
        ]
        print(f"handoffs={found}")
        return found

    def outcome(self) -> str | None:
        value = self.app_db("SELECT outcome FROM conversations WHERE id = ?", self.cid)[
            0
        ][0]
        print(f"outcome={value}")
        return value


def schedule_dump(settings: Settings) -> list[str]:
    conn = sqlite3.connect(settings.SCHEDULING_DB_PATH)
    try:
        return list(conn.iterdump())
    finally:
        conn.close()


def assert_schedule_unchanged(settings: Settings, before: list[str]) -> None:
    after = schedule_dump(settings)
    changed = sorted(set(before) ^ set(after))
    print(f"scheduling db: {len(before)} -> {len(after)} lines, {len(changed)} changed")
    assert changed == [] and len(after) == len(before)


def test_gas_stops_through_the_real_seams(kb_settings: Settings, screen: list[bool]):
    before = schedule_dump(kb_settings)
    chat = Chat(kb_settings, FakeModelProvider(results=recorded("proposal")))

    reply = chat.say(GAS)

    assert reply["text"] == guards.emergency_text(False)
    assert reply["status"] == reply["banner"] == "safety_stop"
    assert reply["choices"] == [] and reply["booking"] is None
    (turn,) = chat.turns()
    assert turn["safety_verdict"] == "emergency"
    assert (turn["tools_called"], turn["has_write"], turn["offered"]) == ("[]", 0, "{}")
    assert_schedule_unchanged(kb_settings, before)
    assert chat.outcome() == "safety_stop"
    assert chat.handoffs() == [("safety_stop", "gas")]
    again = chat.post("Hello?")
    print(f"follow-up message: {again.status_code} {again.json()['error']}")
    assert again.status_code == 409 and again.json()["error"] == "conversation_ended"

    public_id = chat.app_db(
        "SELECT public_id FROM conversations WHERE id = ?", chat.cid
    )[0][0]
    listed = chat.client.get("/handoffs", headers={"Accept": "application/json"})
    (row,) = [
        h for h in listed.json()["handoffs"] if h["conversationPublicId"] == public_id
    ]
    print(
        f"GET /handoffs: kind={row['kind']} reason={row['reason']} "
        f"status={row['status']} conversationPublicId==conversation: True"
    )
    assert (row["kind"], row["status"]) == ("safety_stop", "open")
    assert row["toldCaller"] == reply["text"]
    marked = chat.client.post(
        f"/handoffs/{row['id']}/followed-up", json={"followedUp": True}
    )
    print(
        f"POST followed-up: {marked.status_code} {marked.json()['handoff']['status']}"
    )
    assert marked.status_code == 200
    assert marked.json()["handoff"]["status"] == "followed_up"


def test_burning_smell_asks_first_then_breaker_stops(
    kb_settings: Settings, screen: list[bool]
):
    before = schedule_dump(kb_settings)
    chat = Chat(kb_settings, FakeModelProvider(results=recorded("proposal")))

    first = chat.say(BURNING)

    assert first["text"] == guards.BURNING_FOLLOWUP_TEXT
    assert (first["status"], first["banner"]) == ("active", "none")
    assert first["choices"] == [] and first["booking"] is None
    assert chat.handoffs() == []

    second = chat.say(YES)

    assert second["text"] == guards.emergency_text(False)
    assert second["status"] == second["banner"] == "safety_stop"
    t1, t2 = chat.turns()
    assert (t1["safety_verdict"], t1["tools_called"], t1["offered"]) == (
        "burning_followup",
        "[]",
        "{}",
    )
    assert (t2["safety_verdict"], t2["tools_called"]) == ("emergency", "[]")
    assert chat.outcome() == "safety_stop"
    assert chat.handoffs() == [("safety_stop", "followup_not_clear_no")]
    assert_schedule_unchanged(kb_settings, before)


def test_no_after_the_followup_carries_on(kb_settings: Settings, screen: list[bool]):
    before = schedule_dump(kb_settings)
    model = FakeModelProvider(results=recorded("proposal", "visit_type"))
    chat = Chat(kb_settings, model)
    chat.say(BURNING)

    reply = chat.say(NO)

    assert reply["text"] == RECORDING["visit_type"][-1]["message"]["content"]
    assert (reply["status"], reply["banner"]) == ("active", "none")
    assert reply["choices"] == [] and reply["booking"] is None
    _, t2 = chat.turns()
    assert t2["safety_verdict"] == "safe"
    assert chat.handoffs() == [] and chat.outcome() is None
    assert_schedule_unchanged(kb_settings, before)


def test_a_failing_screen_gets_the_fallback(kb_settings: Settings, screen: list[bool]):
    screen.append(True)
    before = schedule_dump(kb_settings)
    chat = Chat(kb_settings, FakeModelProvider(results=recorded("proposal")))

    reply = chat.say(GAS)

    assert reply["text"] == guards.FALLBACK_TEXT
    assert reply["choices"] == [] and reply["booking"] is None
    assert "request_callback" in reply["actions"]
    (turn,) = chat.turns()
    assert (turn["safety_verdict"], turn["tools_called"], turn["offered"]) == (
        "unscreened",
        "[]",
        "{}",
    )
    assert chat.handoffs() == []
    assert_schedule_unchanged(kb_settings, before)
