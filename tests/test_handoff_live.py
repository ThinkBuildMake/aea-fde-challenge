"""Opt-in: the S32 handoffs against the real agent model and knowledge base.

Needs MERIDIAN_LIVE_TESTS=1 and OPENROUTER_API_KEY; about $0.01 for the module.
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


@pytest.fixture
def live(kb_settings: Settings):
    settings = kb_settings.model_copy(
        update={"OPENROUTER_API_KEY": SecretStr(os.environ["OPENROUTER_API_KEY"])}
    )
    provider = OpenRouterProvider(settings)
    app = create_app(settings, model=provider)
    rebuild_index(app.state.ctx)
    with TestClient(app) as client:
        yield client, settings
    provider.client.close()


def ask(live, text: str) -> tuple[dict[str, Any], dict[str, Any]]:
    client, settings = live
    cid = client.post("/conversations").json()["conversationId"]
    response = client.post(f"/conversations/{cid}/messages", json={"text": text})
    assert response.status_code == 200
    reply = response.json()
    conn = sqlite3.connect(settings.APP_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT kind, reason, intent FROM handoffs WHERE conversation_id = ?",
            (cid,),
        ).fetchone()
    finally:
        conn.close()
    handoff = dict(row) if row else {}
    print(f"\nQ: {text}\nA: {reply['text']}")
    print(f"status={reply['status']} banner={reply['banner']} handoff={handoff}")
    return reply, handoff


def test_a_dispute_is_handed_to_a_supervisor(live):
    reply, handoff = ask(live, "I was charged twice")
    assert (reply["status"], reply["banner"]) == ("handed_off", "handoff")
    assert reply["text"] == guards.SUPERVISOR_DISPUTE_TEXT
    assert reply["actions"] == ["choose_callback_window"]
    assert handoff["reason"] == "billing_dispute"
    assert handoff["kind"] == "supervisor_callback"
    assert re.search(r"charg|twice|double", handoff["intent"], re.IGNORECASE)


def test_asking_for_a_person_hands_over(live):
    reply, handoff = ask(live, "Can I just talk to a person?")
    assert (reply["status"], reply["banner"]) == ("handed_off", "handoff")
    assert reply["text"] == guards.PERSON_TEXT
    assert handoff["reason"] == "caller_asked_for_person"
