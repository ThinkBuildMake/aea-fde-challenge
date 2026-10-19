"""S37 gate: the failure seams through the real modules, with the model provider blocked.

The agent model is the real OpenRouterProvider over an httpx2 transport that refuses every
connection, and the safety classifier raises, so nothing reaches the network.
"""

import time
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient

from app.context import SystemClock
from app.conversation import guards
from app.knowledge.embeddings import FakeEmbedder
from app.knowledge.service import rebuild_index
from app.llm import FakeModelProvider, ModelResult, OpenRouterProvider
from app.main import create_app
from app.scheduling.store import SchedulingUnavailable
from app.settings import Settings
from tests.gate.test_handoff_seams import real_app, rows, send, state_of
from tests.test_turn import assistant, result, tool_call
from tests.test_turn_guards import match


def refuse(request: httpx2.Request) -> httpx2.Response:
    raise httpx2.ConnectError("connection refused", request=request)


@pytest.fixture
def blocked(kb_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """The real modules and caps, with the model provider and the screen unreachable."""

    def no_screen(self: Any, messages: Any, timeout_s: float) -> str:
        raise httpx2.ConnectError("connection refused")

    monkeypatch.setattr(
        "app.safety.service.OpenRouterSafetyClassifier.classify", no_screen
    )
    provider = OpenRouterProvider(
        kb_settings, http_client=httpx2.Client(transport=httpx2.MockTransport(refuse))
    )
    app = create_app(
        kb_settings, model=provider, clock=SystemClock(), embedder=FakeEmbedder()
    )
    rebuild_index(app.state.ctx)
    return TestClient(app, raise_server_exceptions=True)


def test_ten_messages_with_the_provider_blocked(
    blocked: TestClient, kb_settings: Settings
):
    cids: list[str] = []
    for i in range(10):
        cid = blocked.post("/conversations").json()["conversationId"]
        t0 = time.monotonic()
        response = blocked.post(
            f"/conversations/{cid}/messages", json={"text": f"Can I move my visit? {i}"}
        )
        elapsed = time.monotonic() - t0
        reply = response.json()
        turn = rows(
            kb_settings,
            "SELECT fallback_used, error FROM turns WHERE conversation_id = ?",
            cid,
        )[0]
        print(
            f"\nmessage {i + 1}: status={response.status_code} {elapsed:.2f}s "
            f"fallback={reply['text'] == guards.FALLBACK_TEXT} banner={reply['banner']} "
            f"actions={reply['actions']} turn={tuple(turn)}"
        )
        assert response.status_code == 200 and elapsed < 15
        assert reply["text"] == guards.FALLBACK_TEXT
        assert reply["banner"] == "error" and "request_callback" in reply["actions"]
        assert tuple(turn) == (1, "provider_error")
        cids.append(cid)

    picked = blocked.post(
        f"/conversations/{cids[3]}/callback-window", json={"window": "morning"}
    )
    handoffs = rows(kb_settings, "SELECT conversation_id, by_error FROM handoffs")
    outcomes = [state_of(kb_settings, c)["outcome"] for c in cids]
    print(
        f"call back on message 4: status={picked.status_code} handoffs="
        f"{len(handoffs)} by_error={handoffs[0]['by_error']} outcomes={outcomes}"
    )
    assert picked.status_code == 200
    assert [tuple(h) for h in handoffs] == [(cids[3], 1)]
    assert outcomes == [None, None, None, "handoff", *[None] * 6]


def test_call_back_after_a_blocked_provider(blocked: TestClient):
    cid = blocked.post("/conversations").json()["conversationId"]
    send(blocked, cid, "Can I move my visit?")
    picked = blocked.post(
        f"/conversations/{cid}/callback-window", json={"window": "morning"}
    )
    handoff = picked.json()["handoff"]
    print(
        f"\npick={picked.status_code} reason={handoff['reason']} "
        f"byError={handoff['byError']} preferredWindow={handoff['preferredWindow']}"
    )
    assert picked.status_code == 200
    assert (handoff["reason"], handoff["byError"], handoff["preferredWindow"]) == (
        "provider_failure",
        True,
        "morning",
    )


class FailsAfterEscalate(FakeModelProvider):
    """The model escalates, then the provider fails on the next call."""

    def complete(self, messages, *, tools=None, timeout_s):
        if any(m["role"] == "tool" for m in messages):
            raise RuntimeError("provider down")
        return super().complete(messages, tools=tools, timeout_s=timeout_s)


def test_escalate_then_provider_failure_keeps_the_handoff(kb_settings: Settings):
    model = FailsAfterEscalate(
        results=[
            result(
                assistant(
                    calls=[
                        tool_call(
                            "e",
                            "escalate",
                            reason="out_of_scope",
                            intent="Solar panels",
                        )
                    ]
                )
            )
        ]
    )
    client = real_app(kb_settings, model)
    cid = client.post("/conversations").json()["conversationId"]
    reply = send(client, cid, "Can you install solar panels?")
    handoff = rows(
        kb_settings,
        "SELECT reason, by_error FROM handoffs WHERE conversation_id = ?",
        cid,
    )
    after = state_of(kb_settings, cid)
    print(
        f"\nstatus={reply['status']} actions={reply['actions']} text={reply['text']!r} "
        f"handoff={[tuple(h) for h in handoff]} outcome={after['outcome']}"
    )
    assert reply["status"] == "handed_off" and reply["banner"] == "handoff"
    assert reply["actions"] == ["choose_callback_window"]
    assert reply["text"] == guards.HANDOFF_TEXT
    assert [tuple(h) for h in handoff] == [("out_of_scope", 0)]
    assert after["outcome"] == "handoff"


def test_scheduling_down_offers_a_call_back_not_a_booking(
    kb_settings: Settings, monkeypatch: pytest.MonkeyPatch
):
    def down(ctx: Any) -> Any:
        raise SchedulingUnavailable("scheduling database unavailable")

    model = FakeModelProvider(
        results=[
            ModelResult(
                assistant(
                    calls=[
                        tool_call("w", "find_open_windows", serviceType="hvac_repair")
                    ]
                ),
                cost_usd=0.0,
            ),
            result(assistant("You are booked.")),
        ]
    )
    client = real_app(kb_settings, model)
    cid = client.post("/conversations").json()["conversationId"]
    match(kb_settings, cid)
    monkeypatch.setattr("app.scheduling.service.connect", down)
    t0 = time.monotonic()
    reply = send(client, cid, "I need a repair visit")
    elapsed = time.monotonic() - t0
    picked = client.post(
        f"/conversations/{cid}/callback-window", json={"window": "evening"}
    ).json()["handoff"]
    after = state_of(kb_settings, cid)
    print(
        f"\n{elapsed:.2f}s booking={reply['booking']} actions={reply['actions']} "
        f"text={reply['text']!r} handoff reason={picked['reason']} "
        f"byError={picked['byError']} outcome={after['outcome']}"
    )
    assert elapsed < 10 and reply["booking"] is None
    assert "booked" not in reply["text"].lower()
    assert "request_callback" in reply["actions"]
    assert (picked["reason"], picked["byError"]) == ("scheduling_unavailable", True)
    assert after["outcome"] == "handoff"
