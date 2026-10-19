"""Opt-in live check of S15 criterion 1 against the Langfuse project (set MERIDIAN_LIVE_TESTS=1)."""

import os
import sqlite3
import time
from datetime import UTC, datetime, timedelta

import httpx2
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.conversation.tracing import fetch_project_id, trace_link_base
from app.knowledge.embeddings import OpenRouterEmbedder
from app.llm import FakeModelProvider
from app.main import create_app
from app.safety.service import screen_safety as real_screen
from app.settings import Settings
from tests.test_turn import assistant, result, tool_call

pytestmark = pytest.mark.skipif(
    os.environ.get("MERIDIAN_LIVE_TESTS") != "1"
    or not all(
        os.environ.get(k)
        for k in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "OPENROUTER_API_KEY")
    ),
    reason="live tests need MERIDIAN_LIVE_TESTS=1 and the Langfuse and OpenRouter keys",
)


@pytest.fixture
def live(started: Settings, monkeypatch: pytest.MonkeyPatch) -> Settings:
    settings = started.model_copy(
        update={
            "OPENROUTER_API_KEY": SecretStr(os.environ["OPENROUTER_API_KEY"]),
            "LANGFUSE_PUBLIC_KEY": SecretStr(os.environ["LANGFUSE_PUBLIC_KEY"]),
            "LANGFUSE_SECRET_KEY": SecretStr(os.environ["LANGFUSE_SECRET_KEY"]),
            "LANGFUSE_BASE_URL": os.environ.get(
                "LANGFUSE_BASE_URL", started.LANGFUSE_BASE_URL
            ),
        }
    )
    embedder = OpenRouterEmbedder(settings)

    def search(ctx, query, k):
        """The real query embedding (it reports its usage); the passage itself is fixed."""
        from app.types import Passage

        embedder.embed([query])
        return [
            Passage(
                passage_id="p1",
                source_file="pricing/fees.md",
                section="Fees",
                kind="text",
                text="The diagnostic fee is $89.",
                score=0.9,
            )
        ]

    monkeypatch.setattr("app.safety.service.screen_safety", real_screen)
    monkeypatch.setattr("app.knowledge.service.search_knowledge", search)
    return settings


def observations(
    settings: Settings, since: datetime, want: int, **match: str
) -> list[dict]:
    """Observations matching traceId or sessionId, polled until `want` have arrived."""
    assert settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY
    auth = (
        settings.LANGFUSE_PUBLIC_KEY.get_secret_value(),
        settings.LANGFUSE_SECRET_KEY.get_secret_value(),
    )
    for _ in range(24):
        response = httpx2.get(
            f"{settings.LANGFUSE_BASE_URL.rstrip('/')}/api/public/v2/observations",
            params={
                **match,
                "fields": "core,basic,model,usage",
                "fromStartTime": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            auth=auth,
            timeout=20,
        )
        data = response.json().get("data") or []
        if len(data) >= want:
            return data
        time.sleep(5)
    return data


def test_turn_lands_in_langfuse(live: Settings):
    since = datetime.now(UTC) - timedelta(minutes=5)
    model = FakeModelProvider(
        results=[
            result(
                assistant(
                    calls=[tool_call("c1", "search_knowledge", query="diagnostic fee")]
                )
            ),
            result(assistant("The diagnostic fee is $89.")),
        ]
    )
    app = create_app(live, model=model)
    client = TestClient(app)
    cid = client.post("/conversations").json()["conversationId"]
    reply = client.post(
        f"/conversations/{cid}/messages",
        json={"text": "How much is the diagnostic fee?"},
    )
    assert reply.status_code == 200
    app.state.ctx.tracer.flush(30)

    conn = sqlite3.connect(live.APP_DB_PATH)
    trace_id, public_id = conn.execute(
        "SELECT t.trace_id, c.public_id FROM turns t JOIN conversations c "
        "ON c.id = t.conversation_id WHERE t.conversation_id = ?",
        (cid,),
    ).fetchone()
    conn.close()
    assert trace_id and len(trace_id) == 32
    assert live.LANGFUSE_PUBLIC_KEY and live.LANGFUSE_SECRET_KEY
    auth = (
        live.LANGFUSE_PUBLIC_KEY.get_secret_value(),
        live.LANGFUSE_SECRET_KEY.get_secret_value(),
    )

    found = observations(live, since, 5, traceId=trace_id)
    in_session = observations(live, since, 5, sessionId=public_id)
    session_traces = {o["traceId"] for o in in_session}
    print(f"\ntraces in session {public_id}: {sorted(session_traces)}")
    print(f"\nturns.trace_id={trace_id} observations in Langfuse={len(found)}")
    for o in sorted(found, key=lambda o: o["startTime"]):
        print(
            f"  {o['name']:<17} {o['type']:<10} trace_id_matches={o['traceId'] == trace_id} "
            f"session_is_public_id={o['sessionId'] == public_id} "
            f"start={o['startTime']} end={o['endTime']} model={o.get('model')} "
            f"usage={o.get('usageDetails')} cost={o.get('costDetails')}"
        )
    assert session_traces == {trace_id}
    assert {o["traceId"] for o in found} == {trace_id}
    assert {o["sessionId"] for o in found} == {public_id}
    assert sorted(o["name"] for o in found) == [
        "model_call",
        "model_call",
        "safety_screen",
        "search_knowledge",
        "turn",
    ]
    for o in found:
        assert o["startTime"] and o["endTime"]
        if o["name"] in ("safety_screen", "model_call", "search_knowledge"):
            assert o["usageDetails"].get("input", 0) > 0
            assert o["costDetails"]["total"] > 0

    project_id = fetch_project_id(live.LANGFUSE_BASE_URL, auth[0], auth[1], 20)
    assert project_id
    assert app.state.ctx.tracer.project_id == project_id
    link = f"{trace_link_base(live.LANGFUSE_BASE_URL, app.state.ctx.tracer)}/{trace_id}"
    page = httpx2.get(link, timeout=30)
    print(f"\nOpen trace link: {link} -> {page.status_code}")
    assert page.status_code == 200
