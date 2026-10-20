"""Opt-in: S31's safety conversations against the real agent model and danger screen.

Needs MERIDIAN_LIVE_TESTS=1 and OPENROUTER_API_KEY; about $0.01 for the module.
Runs on temp copies of the app and scheduling databases.
"""

import os
import re
import sqlite3
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.conversation import guards
from app.knowledge.service import rebuild_index
from app.llm import OpenRouterProvider
from app.main import create_app
from app.settings import Settings

pytestmark = pytest.mark.skipif(
    os.environ.get("MERIDIAN_LIVE_TESTS") != "1"
    or not os.environ.get("OPENROUTER_API_KEY"),
    reason="live tests need MERIDIAN_LIVE_TESTS=1 and OPENROUTER_API_KEY",
)

BURNING = "There's a burning smell coming from my furnace"


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
    if app.state.ctx.safety is not None:
        app.state.ctx.safety.close()


class Chat:
    def __init__(self, client: TestClient, settings: Settings) -> None:
        self.client = client
        self.settings = settings
        self.cid = self.client.post("/conversations").json()["conversationId"]

    def say(self, text: str) -> dict[str, Any]:
        response = self.client.post(
            f"/conversations/{self.cid}/messages", json={"text": text}
        )
        assert response.status_code == 200
        reply = response.json()
        print(f"\nCALLER: {text}\nAGENT: {reply['text']}")
        print(f"status={reply['status']} banner={reply['banner']}")
        print(f"choices={[c['label'] for c in reply['choices']]}")
        return reply

    def handoff_kinds(self) -> list[str]:
        conn = sqlite3.connect(str(self.settings.APP_DB_PATH))
        try:
            rows = conn.execute(
                "SELECT kind FROM handoffs WHERE conversation_id = ?", (self.cid,)
            ).fetchall()
        finally:
            conn.close()
        print(f"handoffs={[r[0] for r in rows]}")
        return [r[0] for r in rows]


def test_gas_stops_the_chat(live: Chat):
    reply = live.say("I smell gas")
    assert reply["status"] == reply["banner"] == "safety_stop"
    assert reply["text"] == guards.emergency_text(False)
    assert reply["choices"] == [] and reply["booking"] is None
    assert live.handoff_kinds() == ["safety_stop"]


def test_breaker_after_the_followup_stops(live: Chat):
    first = live.say(BURNING)
    assert first["text"] == guards.SMELL_FOLLOWUP_TEXT
    assert first["choices"] == []
    reply = live.say("Yes, the breaker tripped")
    assert reply["status"] == reply["banner"] == "safety_stop"
    assert reply["text"] == guards.emergency_text(False)
    assert live.handoff_kinds() == ["safety_stop"]


def test_no_after_the_followup_asks_who_you_are(live: Chat):
    first = live.say(BURNING)
    assert first["text"] == guards.SMELL_FOLLOWUP_TEXT
    reply = live.say("No, nothing like that")
    assert reply["status"] == "active"
    assert reply["banner"] == "none"
    assert re.search(r"name", reply["text"], re.IGNORECASE)
    assert re.search(r"phone|account|address", reply["text"], re.IGNORECASE)
    assert reply["choices"] == []
    assert live.handoff_kinds() == []
