import sqlite3

from fastapi.testclient import TestClient

from app.llm import FakeModelProvider, ModelResult
from app.main import create_app
from app.settings import Settings
from tests.gate.harness import FakeClock, evaluate_pf2


def tool_turn_latency_ms(settings: Settings, delay_s: float) -> int:
    """A turn with two tool rounds: three model calls, each delayed."""

    def call(call_id: str, name: str, args: str) -> ModelResult:
        message = {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": args},
                }
            ],
        }
        return ModelResult(message)

    clock = FakeClock()
    model = FakeModelProvider(
        results=[
            call(
                "a", "report_status", '{"intent": "policy_question", "resolved": false}'
            ),
            call(
                "b", "report_status", '{"intent": "policy_question", "resolved": true}'
            ),
            ModelResult({"role": "assistant", "content": "done"}),
        ],
        delay_s=delay_s,
        sleep=clock.advance,
    )
    client = TestClient(create_app(settings, model=model, clock=clock))
    cid = client.post("/conversations").json()["conversationId"]
    assert (
        client.post(f"/conversations/{cid}/messages", json={"text": "hi"}).status_code
        == 200
    )
    conn = sqlite3.connect(settings.APP_DB_PATH)
    try:
        return conn.execute("SELECT latency_ms FROM turns").fetchone()[0]
    finally:
        conn.close()


def test_tool_turn_latency_within_pf2(started: Settings):
    latency = tool_turn_latency_ms(started, 2.0)
    assert latency == 6000
    verdict = evaluate_pf2([latency])
    assert verdict.passed, verdict.message


def test_slow_tool_turn_fails_pf2(started: Settings):
    latency = tool_turn_latency_ms(started, 4.0)
    verdict = evaluate_pf2([latency])
    assert verdict.passed is False
    assert "PF-2" in verdict.message and "10 s" in verdict.message
