"""Opt-in tests against the real agent model: MERIDIAN_LIVE_TESTS=1 and OPENROUTER_API_KEY."""

import copy
import json
import os
import sqlite3
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.llm import ModelProvider, ModelResult, OpenRouterProvider
from app.main import create_app
from app.settings import Settings
from app.types import Passage

pytestmark = pytest.mark.skipif(
    os.environ.get("MERIDIAN_LIVE_TESTS") != "1"
    or not os.environ.get("OPENROUTER_API_KEY"),
    reason="live tests need MERIDIAN_LIVE_TESTS=1 and OPENROUTER_API_KEY",
)


class RecordingProvider:
    def __init__(self, inner: ModelProvider) -> None:
        self.inner = inner
        self.sent: list[list[dict[str, Any]]] = []

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        timeout_s: float,
    ) -> ModelResult:
        self.sent.append(copy.deepcopy(messages))
        return self.inner.complete(messages, tools=tools, timeout_s=timeout_s)


@pytest.fixture
def live(started: Settings, monkeypatch: pytest.MonkeyPatch):
    passage = Passage(
        passage_id="fees-1",
        source_file="pricing/fees.md",
        section="Fees",
        kind="text",
        text="The diagnostic fee is $89 per visit.",
        score=0.95,
    )
    monkeypatch.setattr(
        "app.knowledge.service.search_knowledge", lambda ctx, query, k: [passage]
    )
    settings = started.model_copy(
        update={"OPENROUTER_API_KEY": SecretStr(os.environ["OPENROUTER_API_KEY"])}
    )
    provider = OpenRouterProvider(settings)
    model = RecordingProvider(provider)
    client = TestClient(create_app(settings, model=model))
    cid = client.post("/conversations").json()["conversationId"]
    yield client, cid, model, settings
    provider.client.close()


def turn_row(settings: Settings, seq: int) -> sqlite3.Row:
    conn = sqlite3.connect(settings.APP_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute("SELECT * FROM turns WHERE seq = ?", (seq,)).fetchone()
    finally:
        conn.close()


def test_real_model_answers_fee_with_search_knowledge(live):
    client, cid, _, settings = live
    response = client.post(
        f"/conversations/{cid}/messages", json={"text": "What is the diagnostic fee?"}
    )
    assert response.status_code == 200
    assert "89" in response.json()["text"]
    tools = json.loads(turn_row(settings, 1)["tools_called"])
    assert "search_knowledge" in [t["name"] for t in tools]


def test_second_turn_replays_first_exactly(live):
    client, cid, model, settings = live
    first = client.post(
        f"/conversations/{cid}/messages", json={"text": "What is the diagnostic fee?"}
    )
    assert first.status_code == 200
    calls_after_first = len(model.sent)
    second = client.post(
        f"/conversations/{cid}/messages",
        json={"text": "Thanks. And is that per visit?"},
    )
    assert second.status_code == 200
    assert second.json()["text"]
    stored = json.loads(turn_row(settings, 1)["model_messages"])
    assert any("reasoning_details" in m for m in stored if m["role"] == "assistant")
    sent = model.sent[calls_after_first]
    assert sent[0]["role"] == "system"
    assert sent[1 : 1 + len(stored)] == stored
    assert sent[1 + len(stored)] == {
        "role": "user",
        "content": "Thanks. And is that per visit?",
    }
