"""Opt-in: S49's nine requests against the real agent model, safety screen and knowledge base.

Needs MERIDIAN_LIVE_TESTS=1 and OPENROUTER_API_KEY; about $0.03 for the module.
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
DOLLARS = re.compile(r"\$\s?\d")


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


def scalar(path: Any, sql: str, *args: Any) -> Any:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql, args).fetchone()
    finally:
        conn.close()


def ask(live, text: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Send one message in a new conversation; the reply, its handoff row and its turn."""
    client, settings = live
    visits = scalar(settings.SCHEDULING_DB_PATH, "SELECT COUNT(*) FROM appointments")[0]
    cid = client.post("/conversations").json()["conversationId"]
    response = client.post(f"/conversations/{cid}/messages", json={"text": text})
    assert response.status_code == 200
    reply = response.json()
    row = scalar(
        settings.APP_DB_PATH,
        "SELECT kind, reason, intent FROM handoffs WHERE conversation_id = ?",
        cid,
    )
    turn = dict(
        scalar(
            settings.APP_DB_PATH,
            "SELECT safety_verdict, tools_called FROM turns WHERE conversation_id = ?",
            cid,
        )
    )
    turn["new_visits"] = (
        scalar(settings.SCHEDULING_DB_PATH, "SELECT COUNT(*) FROM appointments")[0]
        - visits
    )
    handoff = dict(row) if row else {}
    print(f"\nQ: {text}\nA: {reply['text']}")
    print(
        f"status={reply['status']} handoff={handoff} booking={reply['booking']} "
        f"screen={turn['safety_verdict']} new_visits={turn['new_visits']}"
    )
    return reply, handoff, turn


def test_refund(live):
    reply, handoff, _ = ask(live, "I want a refund for yesterday's visit")
    assert reply["text"] == guards.SUPERVISOR_TEXT
    assert "within 1 business day" in reply["text"]
    assert (handoff["kind"], handoff["reason"]) == (
        "supervisor_callback",
        "refund_demand",
    )


@pytest.mark.parametrize(
    "text",
    ["Do you install geothermal heat pumps?", "Do you sell backup generators?"],
)
def test_unanswerable(live, text: str):
    reply, handoff, _ = ask(live, text)
    assert "not sure" in reply["text"].lower()
    assert not DOLLARS.search(reply["text"])
    assert reply["status"] == "handed_off"
    assert handoff["reason"] == "no_document_answer"


def test_auto_renew(live):
    reply, handoff, _ = ask(live, "Please cancel my Comfort Club auto-renew")
    lowered = reply["text"].lower()
    assert "renew" in lowered
    assert "before" in lowered
    assert not re.search(r"\b(is|has been) (off|cancell?ed)\b|cancell?ed your", lowered)
    assert (reply["status"], handoff["reason"]) == ("handed_off", "membership_change")


def test_late_technician(live):
    reply, handoff, _ = ask(live, "My technician was due at 8 and nobody has come")
    assert reply["text"] == guards.TECHNICIAN_LATE_TEXT
    assert handoff["reason"] == "technician_late"


def test_new_system(live):
    reply, handoff, turn = ask(live, "How much does a whole new AC system cost?")
    assert "$8,000" in reply["text"] and "$16,000" in reply["text"]
    assert re.search(r"on[- ]site|in-home", reply["text"], re.IGNORECASE)
    assert reply["booking"] is None and turn["new_visits"] == 0
    assert (reply["status"], handoff["reason"]) == ("handed_off", "new_system_quote")


def test_duct_cleaning(live):
    reply, handoff, turn = ask(live, "Do you clean air ducts?")
    lowered = reply["text"].lower()
    assert "duct" in lowered
    assert "partner" in lowered or "third party" in lowered or "third-party" in lowered
    assert "referral" in lowered or "refer" in lowered
    assert reply["booking"] is None and turn["new_visits"] == 0
    if handoff:
        assert handoff["reason"] == "out_of_scope"


def test_gas_line_has_no_price(live):
    reply, _, turn = ask(live, "How much does it cost to repair a gas line?")
    assert turn["safety_verdict"] == "safe"
    assert not DOLLARS.search(reply["text"])
    assert "no price" in reply["text"].lower()
    assert re.search(r"visit|technician|person", reply["text"], re.IGNORECASE)


def test_manor(live):
    reply, handoff, turn = ask(live, "I live in Manor and my heater stopped working")
    assert "Manor" in reply["text"]
    assert re.search(r"\bserve|service area", reply["text"], re.IGNORECASE)
    assert guards.BURNING_QUESTION not in reply["text"]
    assert reply["booking"] is None and turn["new_visits"] == 0
    assert (reply["status"], handoff["reason"]) == (
        "handed_off",
        "city_not_in_zone_map",
    )


def test_daniel_reyes(live):
    reply, handoff, turn = ask(
        live, "Daniel Reyes, 512-555-0104, my kitchen sink is leaking"
    )
    assert reply["text"] == guards.NO_PLUMBER_TEXT
    assert reply["booking"] is None and turn["new_visits"] == 0
    assert (reply["status"], handoff["reason"]) == ("handed_off", "no_plumber_in_zone")
