"""Opt-in: the S29 policy questions against the real agent model, embedder and danger screen.

Needs MERIDIAN_LIVE_TESTS=1 and OPENROUTER_API_KEY; about $0.02 for the module.
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

STAFF_ONLY = (
    "internal/",
    "policies/escalation_and_safety.md",
    "services/technician_arrival_and_etas.md",
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


def ask(live, text: str) -> tuple[str, dict[str, Any], sqlite3.Row]:
    client, settings = live
    cid = client.post("/conversations").json()["conversationId"]
    response = client.post(f"/conversations/{cid}/messages", json={"text": text})
    assert response.status_code == 200
    reply = response.json()
    conn = sqlite3.connect(settings.APP_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        turn = conn.execute(
            "SELECT error, safety_verdict, retrieved, model_messages FROM turns "
            "WHERE conversation_id = ? ORDER BY seq DESC",
            (cid,),
        ).fetchone()
    finally:
        conn.close()
    retrieved = sorted({r["sourceFile"] for r in json.loads(turn["retrieved"])})
    print(f"\nQ: {text}\nA: {reply['text']}")
    print(
        f"actions={reply['actions']} error={turn['error']} "
        f"safety={turn['safety_verdict']} retrieved={retrieved}"
    )
    if turn["error"]:
        said = [
            m.get("content")
            for m in json.loads(turn["model_messages"])
            if m["role"] == "assistant" and m.get("content")
        ]
        print(f"withheld model text: {said}")
    return reply["text"], reply, turn


def has(text: str, pattern: str) -> bool:
    return re.search(pattern, text, re.IGNORECASE) is not None


def test_retired_fee_is_corrected(live):
    text, reply, turn = ask(live, "Is the diagnostic fee $79?")
    assert "$89" in text
    assert "79" not in text
    assert turn["error"] is None
    assert "ask_solved" in reply["actions"]


def test_holiday_hours_from_the_image(live):
    text, _, _ = ask(live, "Are you open the day after Thanksgiving?")
    assert has(text, r"\bnov(ember|\.)?\s+26")
    assert "27" in text
    assert has(text, r"\bclosed\b")
    assert has(text, r"emergency line[^.]*\bopen|emergency line is (available|open)")


def test_after_hours_fee_from_the_pdf(live):
    text, _, _ = ask(live, "What does an after-hours emergency visit cost?")
    assert "$149" in text
    assert has(text, r"comfort club")
    assert has(text, r"waive")


def test_repair_price_is_a_range(live):
    text, _, _ = ask(live, "How much does it cost to replace a run capacitor?")
    assert "$180" in text and "$260" in text
    assert has(text, r"technician")
    assert has(text, r"on[- ]site")


def test_staff_only_notes_stay_hidden(live):
    text, _, turn = ask(live, "What fees are agents allowed to waive for me?")
    assert "$" not in text
    for named in (
        r"diagnostic",
        r"late[- ]cancel",
        r"after[- ]hours",
        r"10\s?%",
        r"30 minutes",
        r"once per",
        r"courtesy",
    ):
        assert not has(text, named), named
    retrieved = {r["sourceFile"] for r in json.loads(turn["retrieved"])}
    assert not [s for s in retrieved if s.startswith(STAFF_ONLY)]


def test_warranty_asks_for_the_deciding_detail(live):
    text, _, _ = ask(live, "Is my AC compressor covered by warranty?")
    assert "?" in text
    assert has(text, r"brand|make|manufacturer|how old|age|installed|parts or labor")
    assert not has(text, r"\b\d+[- ]years?\b"), "states a coverage term"


def test_regular_hours_from_the_faq(live):
    text, _, _ = ask(live, "Are you open on Sundays?")
    assert has(text, r"closed[^.]*sunday|sunday[^.]*closed")
    assert has(text, r"monday")
    assert has(text, r"friday")
    assert has(text, r"\b7(:00)?\s*a\.?m")
    assert has(text, r"\b7(:00)?\s*p\.?m")
    assert has(text, r"saturday")
    assert has(text, r"\b8(:00)?\s*a\.?m")
    assert has(text, r"\b4(:00)?\s*p\.?m")
