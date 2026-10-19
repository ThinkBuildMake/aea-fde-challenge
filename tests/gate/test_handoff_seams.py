"""S32 gate: an escalation through the real Safety, Conversation, Knowledge and Follow-ups.

Only the network edges are scripted: the safety classifier's reply (autouse stub), the
embedder (FakeEmbedder) and the agent model (a hand-written recording).
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
from app.settings import Settings
from tests.gate.harness import FakeClock
from tests.test_turn_guards import match

RECORDED = Path(__file__).parent / "recorded"


def recording(name: str) -> list[ModelResult]:
    """A recorded model turn from tests/gate/recorded/<name>.json."""
    return [
        ModelResult(
            dict(entry["message"]),
            prompt_tokens=entry["prompt_tokens"],
            completion_tokens=entry["completion_tokens"],
            cost_usd=entry["cost"],
        )
        for entry in json.loads((RECORDED / f"{name}.json").read_text())["messages"]
    ]


def real_app(settings: Settings, model: FakeModelProvider) -> TestClient:
    app = create_app(settings, model=model, clock=FakeClock(), embedder=FakeEmbedder())
    rebuild_index(app.state.ctx)
    return TestClient(app)


def rows(settings: Settings, sql: str, *args: Any) -> list[sqlite3.Row]:
    conn = sqlite3.connect(settings.APP_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def send(client: TestClient, cid: str, text: str, **extra: Any) -> dict[str, Any]:
    response = client.post(
        f"/conversations/{cid}/messages", json={"text": text, **extra}
    )
    assert response.status_code == 200
    return response.json()


def state_of(settings: Settings, cid: str) -> dict[str, Any]:
    return {
        "handoffs": rows(
            settings, "SELECT COUNT(*) FROM handoffs WHERE conversation_id = ?", cid
        )[0][0],
        "outcome": rows(
            settings, "SELECT outcome FROM conversations WHERE id = ?", cid
        )[0][0],
        "turns": rows(
            settings, "SELECT COUNT(*) FROM turns WHERE conversation_id = ?", cid
        )[0][0],
    }


def test_a_recorded_escalation_commits_handoff_and_outcome_together(
    kb_settings: Settings,
):
    client = real_app(
        kb_settings, FakeModelProvider(results=recording("charged_twice"))
    )
    cid = client.post("/conversations").json()["conversationId"]
    reply = send(client, cid, "I was charged twice")
    after = state_of(kb_settings, cid)
    print(f"\nreply status={reply['status']} banner={reply['banner']}")
    print(f"after the turn: {after}")
    assert reply["status"] == "handed_off" and reply["banner"] == "handoff"
    assert after == {"handoffs": 1, "outcome": "handoff", "turns": 1}


def test_db_failing_mid_handoff_leaves_no_handoff(
    kb_settings: Settings, monkeypatch: pytest.MonkeyPatch
):
    def failing(tx: sqlite3.Connection, conversation_id: str) -> None:
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr("app.conversation.service.end_with_handoff", failing)
    client = real_app(
        kb_settings, FakeModelProvider(results=recording("charged_twice"))
    )
    cid = client.post("/conversations").json()["conversationId"]
    reply = send(client, cid, "I was charged twice")
    after = state_of(kb_settings, cid)
    print(f"\nreply status={reply['status']} banner={reply['banner']}")
    print(f"text={reply['text']!r}\nafter the turn: {after}")
    assert reply["text"] == guards.FALLBACK_TEXT
    assert (reply["status"], reply["banner"]) == ("active", "error")
    assert after == {"handoffs": 0, "outcome": None, "turns": 0}


def test_handoff_record_is_complete(kb_settings: Settings):
    client = real_app(
        kb_settings, FakeModelProvider(results=recording("charged_twice"))
    )
    cid = client.post("/conversations").json()["conversationId"]
    match(kb_settings, cid)
    reply = send(client, cid, "I was charged twice")
    picked = client.post(
        f"/conversations/{cid}/callback-window", json={"window": "afternoon"}
    )
    assert picked.status_code == 200
    row = dict(
        rows(
            kb_settings,
            "SELECT kind, reason, intent, told_caller, preferred_window, caller_name, "
            "caller_phone FROM handoffs WHERE conversation_id = ?",
            cid,
        )[0]
    )
    print(f"\nhandoff row: {row}")
    assert row == {
        "kind": "supervisor_callback",
        "reason": "billing_dispute",
        "intent": "Charged twice for the same visit",
        "told_caller": reply["text"],
        "preferred_window": "afternoon",
        "caller_name": "Omar Patel",
        "caller_phone": "512-555-0102",
    }


def test_policy_and_failure_handoffs_count_apart(kb_settings: Settings):
    settings = kb_settings.model_copy(update={"DEMO_FAULT_INJECTION": True})
    client = real_app(settings, FakeModelProvider(results=recording("charged_twice")))
    dispute = client.post("/conversations").json()["conversationId"]
    send(client, dispute, "I was charged twice")
    outage = client.post("/conversations").json()["conversationId"]
    send(client, outage, "Is the diagnostic fee $89?", simulateOutage=True)
    client.post(f"/conversations/{outage}/callback-window", json={"window": "morning"})
    found = {
        r["conversation_id"]: (r["reason"], r["by_error"], r["error"])
        for r in rows(
            settings,
            "SELECT h.conversation_id, h.reason, h.by_error, t.error FROM handoffs h "
            "JOIN turns t ON t.conversation_id = h.conversation_id",
        )
    }
    print(f"\ndispute: {found[dispute]}\noutage: {found[outage]}")
    assert found[dispute] == ("billing_dispute", 0, None)
    assert found[outage] == ("provider_failure", 1, "provider_error")
