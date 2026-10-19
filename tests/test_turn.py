import json
import re
import sqlite3
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.llm import FakeModelProvider, ModelResult
from app.main import create_app
from app.safety import service as safety
from app.settings import Settings
from app.types import Passage, RedactResult
from tests.gate.harness import FakeClock

LONG_DIGITS = re.compile(r"(?:\d[ -]?){12,18}\d")


def tool_call(call_id: str, name: str, **args: Any) -> dict[str, Any]:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


def assistant(content: str = "", calls: list[dict[str, Any]] | None = None):
    message: dict[str, Any] = {
        "role": "assistant",
        "content": content,
        "reasoning_details": [{"type": "reasoning.encrypted", "data": "x"}],
    }
    if calls:
        message["tool_calls"] = calls
    return message


def result(message: dict[str, Any], cost: float | None = 0.0001) -> ModelResult:
    return ModelResult(message, prompt_tokens=100, completion_tokens=20, cost_usd=cost)


@pytest.fixture(autouse=True)
def one_passage(monkeypatch: pytest.MonkeyPatch):
    passage = Passage(
        passage_id="p1",
        source_file="pricing/fees.md",
        section="Fees",
        kind="text",
        text="The diagnostic fee is $89.",
        score=0.9,
    )
    monkeypatch.setattr(
        "app.knowledge.service.search_knowledge", lambda ctx, query, k: [passage]
    )


def client_for(settings: Settings, model: FakeModelProvider, clock=None):
    return TestClient(create_app(settings, model=model, clock=clock or FakeClock()))


def new_conversation(client: TestClient) -> str:
    return client.post("/conversations").json()["conversationId"]


def say(client: TestClient, cid: str, text: str):
    response = client.post(f"/conversations/{cid}/messages", json={"text": text})
    assert response.status_code == 200
    return response.json()


def rows(settings: Settings, sql: str, *args: Any) -> list[sqlite3.Row]:
    conn = sqlite3.connect(settings.APP_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def search_then_answer(n: int, cost: float | None = 0.0001) -> list[ModelResult]:
    out: list[ModelResult] = []
    for i in range(n):
        out.append(
            result(
                assistant(calls=[tool_call(f"c{i}", "search_knowledge", query="fee")]),
                cost,
            )
        )
        out.append(result(assistant("It is $89."), cost))
    return out


def test_every_turn_is_stored_whole(started: Settings):
    model = FakeModelProvider(results=search_then_answer(3))
    client = client_for(started, model)
    cid = new_conversation(client)
    for i in range(3):
        say(client, cid, f"question {i}")
    turns = rows(started, "SELECT * FROM turns WHERE conversation_id = ?", cid)
    assert len(turns) == 3
    for turn in turns:
        assert turn["latency_ms"] is not None
        tools = json.loads(turn["tools_called"])
        assert tools and set(tools[0]) == {"name", "ok", "ms", "error"}
        assert tools[0]["name"] == "search_knowledge" and tools[0]["ok"] is True
        retrieved = json.loads(turn["retrieved"])
        assert retrieved[0]["sourceFile"] == "pricing/fees.md"
        assert set(retrieved[0]) == {"passageId", "sourceFile", "score"}
        assert turn["cost_usd"] > 0
        assert turn["cost_source"] == "reported"
    conv = rows(started, "SELECT * FROM conversations WHERE id = ?", cid)[0]
    assert conv["turn_count"] == 3
    assert conv["cost_usd"] == pytest.approx(sum(t["cost_usd"] for t in turns))


def test_cost_is_estimated_without_a_reported_cost(started: Settings):
    started.MODEL_PRICES = {started.AGENT_MODEL: {"input": 0.5, "output": 3.0}}
    model = FakeModelProvider(results=[result(assistant("hello"), cost=None)])
    client = client_for(started, model)
    cid = new_conversation(client)
    say(client, cid, "hi")
    turn = rows(started, "SELECT * FROM turns WHERE conversation_id = ?", cid)[0]
    assert turn["cost_source"] == "estimated"
    assert turn["cost_usd"] == pytest.approx((100 * 0.5 + 20 * 3.0) / 1e6)


def test_intent_is_recorded(started: Settings):
    def report(call_id: str, intent: str) -> list[ModelResult]:
        return [
            result(
                assistant(
                    calls=[
                        tool_call(
                            call_id, "report_status", intent=intent, resolved=False
                        )
                    ]
                )
            ),
            result(assistant("ok")),
        ]

    script = (
        report("a", "book_visit")
        + report("b", "membership_question")
        + report("c", "book_visit")
    )
    client = client_for(started, FakeModelProvider(results=script))
    cid = new_conversation(client)
    for text in ("book me", "membership?", "book again"):
        say(client, cid, text)
        if text == "membership?":
            conv = rows(started, "SELECT * FROM conversations WHERE id = ?", cid)[0]
            assert conv["intent"] == "membership_question"
            assert json.loads(conv["intents_seen"]) == [
                "book_visit",
                "membership_question",
            ]
    conv = rows(started, "SELECT * FROM conversations WHERE id = ?", cid)[0]
    assert conv["intent"] == "book_visit"
    assert json.loads(conv["intents_seen"]) == ["book_visit", "membership_question"]


def test_card_number_never_reaches_model_or_db(
    started: Settings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    def redact(text: str) -> RedactResult:
        cleaned = LONG_DIGITS.sub("[card number removed]", text)
        return RedactResult(text=cleaned, removed=cleaned != text)

    monkeypatch.setattr(safety, "redact_card_numbers", redact)
    model = FakeModelProvider(["Noted."])
    client = client_for(started, model)
    cid = new_conversation(client)
    say(client, cid, "My card is 4111 1111 1111 1111")
    sent = json.dumps(model.received)
    assert "card number removed" in sent
    assert not LONG_DIGITS.search(sent)
    turn = rows(started, "SELECT * FROM turns WHERE conversation_id = ?", cid)[0]
    assert "card number removed" in turn["caller_text"]
    for column in ("caller_text", "model_messages", "reply_text"):
        assert not LONG_DIGITS.search(turn[column])
    captured = capsys.readouterr()
    assert not LONG_DIGITS.search(captured.out + captured.err)
    assert "My card is" not in captured.out + captured.err


def test_turn_replays_history_and_stores_valid_sequence(started: Settings):
    model = FakeModelProvider(results=search_then_answer(2))
    client = client_for(started, model)
    cid = new_conversation(client)
    say(client, cid, "first")
    say(client, cid, "second")
    turn1 = rows(started, "SELECT model_messages FROM turns WHERE seq = 1")[0]
    stored = json.loads(turn1["model_messages"])
    assert stored[0] == {"role": "user", "content": "first"}
    # turn 2's first call: system + turn 1's stored messages + the new user message
    sent = model.received[2]
    assert sent[0]["role"] == "system"
    assert sent[1 : 1 + len(stored)] == stored
    assert sent[1 + len(stored) :] == [{"role": "user", "content": "second"}]
    ids = [c["id"] for m in stored for c in m.get("tool_calls", [])]
    answered = [m["tool_call_id"] for m in stored if m["role"] == "tool"]
    assert ids and ids == answered
    assert "reasoning_details" in stored[1]


def test_unknown_tool_still_gets_a_result(started: Settings):
    script = [
        result(assistant(calls=[tool_call("z", "no_such_tool")])),
        result(assistant("sorry")),
    ]
    client = client_for(started, FakeModelProvider(results=script))
    cid = new_conversation(client)
    say(client, cid, "hi")
    turn = rows(started, "SELECT * FROM turns")[0]
    assert json.loads(turn["tools_called"])[0]["ok"] is False
    assert [m["role"] for m in json.loads(turn["model_messages"])] == [
        "user",
        "assistant",
        "tool",
        "assistant",
    ]


def test_first_turn_latency_is_stored(started: Settings):
    clock = FakeClock()
    model = FakeModelProvider(["hi"], delay_s=2.0, sleep=clock.advance)
    client = client_for(started, model, clock)
    cid = new_conversation(client)
    body = say(client, cid, "hello")
    turn = rows(started, "SELECT latency_ms FROM turns WHERE conversation_id = ?", cid)[
        0
    ]
    assert turn["latency_ms"] == 2000
    assert body["turn"] == {"seq": 1, "latencyMs": 2000}


def test_instructions_carry_the_policy_rules(started: Settings):
    model = FakeModelProvider(results=[result(assistant("hello"))])
    client = client_for(started, model)
    say(client, new_conversation(client), "Is the diagnostic fee $79?")
    system = model.received[0][0]
    assert system["role"] == "system"
    for rule in (
        "resolved is true when the caller's need is fully met this turn",
        "never repeat the caller's figure",
        "unless a tool result for the caller's own record gives that figure",
        "give every day's hours and the closed days",
        "the exact dates the document lists and whether the emergency line is open",
        "the technician confirms pricing on site",
        "never as something you or Meridian will do",
        "do not name or list any fee, waiver or discount",
        "Ask only for a detail the caller has not given",
        "answer parts and labor separately",
    ):
        assert rule in system["content"], rule
