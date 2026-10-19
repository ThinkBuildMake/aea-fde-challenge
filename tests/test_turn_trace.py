"""S15: each turn becomes one scrubbed trace; tracing never touches the turn."""

import dataclasses
import json
import socket
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app import usage
from app.conversation import tracing
from app.conversation.tracing import RecordingTracer, TurnTrace
from app.llm import FakeModelProvider, ModelResult
from app.main import create_app
from app.settings import Settings
from app.types import Passage, Verdict
from tests.gate.harness import FakeClock
from tests.test_turn import (
    LONG_DIGITS,
    assistant,
    new_conversation,
    result,
    rows,
    say,
    tool_call,
)

PASSAGE = Passage(
    passage_id="p1",
    source_file="pricing/fees.md",
    section="Fees",
    kind="text",
    text="The diagnostic fee is $89.",
    score=0.9,
)


@pytest.fixture(autouse=True)
def search_and_screen_report_usage(monkeypatch: pytest.MonkeyPatch):
    """The search embeds its query and the screen calls its model; both report usage as the real ones do."""

    def search(ctx, query, k):
        usage.report(usage.Usage(input_tokens=5, cost_usd=0.0000001))
        return [PASSAGE]

    def screen(ctx, text, recent_turns, follow_up_pending):
        usage.report(usage.Usage(input_tokens=120, output_tokens=8, cost_usd=0.00002))
        return Verdict(verdict="safe", reason="no_hazard")

    monkeypatch.setattr("app.knowledge.service.search_knowledge", search)
    monkeypatch.setattr("app.safety.service.screen_safety", screen)


def traced(settings: Settings, results: list[ModelResult] | None = None, **kw: Any):
    tracer = kw.pop("tracer", None) or RecordingTracer()
    model = kw.pop("model", None) or FakeModelProvider(results=results)
    app = create_app(settings, model=model, clock=FakeClock(), tracer=tracer)
    return TestClient(app), tracer


def search_turn() -> list[ModelResult]:
    return [
        result(
            assistant(
                calls=[
                    tool_call("c1", "search_knowledge", query="diagnostic fee"),
                    tool_call(
                        "c2", "report_status", intent="policy_question", resolved=True
                    ),
                ]
            )
        ),
        result(assistant("It is $89.")),
    ]


def public_id(settings: Settings, cid: str) -> str:
    return rows(settings, "SELECT public_id FROM conversations WHERE id = ?", cid)[0][0]


def pin_public_id(settings: Settings, cid: str, value: str = "pub-session-abc") -> None:
    import sqlite3

    conn = sqlite3.connect(settings.APP_DB_PATH)
    with conn:
        conn.execute(
            "UPDATE conversations SET public_id = ? WHERE id = ?", (value, cid)
        )
    conn.close()


def dumped(trace: TurnTrace) -> str:
    return json.dumps(dataclasses.asdict(trace), default=str)


def strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in (*strings(k), *strings(v))]
    if isinstance(value, list | tuple):
        return [s for v in value for s in strings(v)]
    return []


def test_one_trace_per_turn(started: Settings):
    client, tracer = traced(started, search_turn())
    cid = new_conversation(client)
    say(client, cid, "How much is the diagnostic fee?")

    assert len(tracer.traces) == 1
    trace = tracer.traces[0]
    assert trace.session_id == public_id(started, cid)
    names = [o.name for o in trace.observations]
    assert sorted(names) == [
        "model_call",
        "model_call",
        "report_status",
        "safety_screen",
        "search_knowledge",
    ]
    by_name = {o.name: o for o in trace.observations}
    screen, search = by_name["safety_screen"], by_name["search_knowledge"]
    calls = [o for o in trace.observations if o.name == "model_call"]
    assert (screen.kind, screen.model) == ("generation", started.SAFETY_MODEL)
    assert (screen.input_tokens, screen.output_tokens, screen.cost_usd) == (
        120,
        8,
        0.00002,
    )
    assert (search.kind, search.model) == ("tool", started.EMBEDDING_MODEL)
    assert (search.input_tokens, search.cost_usd) == (5, 0.0000001)
    for call in calls:
        assert (call.kind, call.model) == ("generation", started.AGENT_MODEL)
        assert (call.input_tokens, call.output_tokens, call.cost_usd) == (
            100,
            20,
            0.0001,
        )
    for o in trace.observations:
        assert trace.start <= o.start <= o.end <= trace.end
    stored = rows(started, "SELECT trace_id FROM turns WHERE conversation_id = ?", cid)
    assert [r["trace_id"] for r in stored] == tracer.ids
    print(
        f"\ntraces={len(tracer.traces)} session_is_public_id="
        f"{trace.session_id == public_id(started, cid)} turns.trace_id={stored[0]['trace_id']}"
    )
    for o in trace.observations:
        ms = (o.end - o.start).total_seconds() * 1000
    print(
        f"  {o.name:<17} {o.kind:<10} ms={ms:.1f} tokens_in={o.input_tokens} "
        f"tokens_out={o.output_tokens} cost_usd={o.cost_usd}"
    )


def test_card_number_never_in_trace(started: Settings, monkeypatch: pytest.MonkeyPatch):
    def failing_search(ctx, query, k):
        raise ValueError("lookup 4111111111111111 failed")

    monkeypatch.setattr("app.knowledge.service.search_knowledge", failing_search)
    client, tracer = traced(
        started,
        [
            result(assistant(calls=[tool_call("c1", "search_knowledge", query="q")])),
            result(assistant("Your card 4111111111111111 is noted.")),
        ],
    )
    cid = new_conversation(client)
    pin_public_id(started, cid)
    say(client, cid, "My card is 4111 1111 1111 1111")

    text = dumped(tracer.traces[0])
    print(f"\ndigit runs of 13-19 in trace: {LONG_DIGITS.findall(text)}")
    assert LONG_DIGITS.search(text) is None
    assert "[card number removed]" in text and "[digits removed]" in text


@pytest.mark.parametrize("fails", [False, True])
def test_secret_id_never_in_trace(started: Settings, fails: bool):
    model = FakeModelProvider(fail_with=RuntimeError("down")) if fails else None
    client, tracer = traced(started, search_turn(), model=model)
    cid = new_conversation(client)
    say(client, cid, f"my conversation is {cid}")

    values = strings(dataclasses.asdict(tracer.traces[0]))
    print(
        f"\nstring values checked={len(values)} holding the secret id={sum(cid in v for v in values)}"
    )
    assert values and not any(cid in v for v in values)


def test_no_raw_model_messages_in_trace(started: Settings):
    def noted(message: dict[str, Any]) -> dict[str, Any]:
        return {
            **message,
            "reasoning": "REASONING-NOTE-MARKER",
            "reasoning_details": [
                {"type": "reasoning.text", "text": "REASONING-DETAIL-MARKER"}
            ],
        }

    client, tracer = traced(
        started,
        [
            result(
                noted(
                    assistant(
                        calls=[tool_call("c1", "search_knowledge", query="ARGS-MARKER")]
                    )
                )
            ),
            result(noted(assistant("It is $89."))),
        ],
    )
    cid = new_conversation(client)
    say(client, cid, "How much is the diagnostic fee?")

    trace = tracer.traces[0]
    text = dumped(trace)
    markers = [
        "REASONING-NOTE-MARKER",
        "REASONING-DETAIL-MARKER",
        "ARGS-MARKER",
        "Meridian assistant",
    ]
    found = [m for m in markers if m in text]
    keys = {"role", "tool_calls", "reasoning", "reasoning_details"} & {
        k for o in trace.observations for k in o.metadata
    } | ({"role", "tool_calls", "reasoning", "reasoning_details"} & set(trace.metadata))
    print(f"\nmarkers found in trace: {found}; message keys found: {sorted(keys)}")
    assert found == [] and keys == set()


def refused_port() -> socket.socket:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    return sock


def test_langfuse_outage_never_touches_a_turn(started: Settings, capsys):
    sock = refused_port()
    settings = started.model_copy(
        update={
            "LANGFUSE_PUBLIC_KEY": SecretStr("test-public"),
            "LANGFUSE_SECRET_KEY": SecretStr("test-secret"),
            "LANGFUSE_BASE_URL": f"http://127.0.0.1:{sock.getsockname()[1]}",
        }
    )
    tracer = tracing.tracer_for(settings, timeout_s=1.0)
    client, _ = traced(
        settings, [result(assistant("Hello! How can I help?"))], tracer=tracer
    )
    cid = new_conversation(client)
    reply = say(client, cid, "hello")
    assert tracer is not None
    tracer.flush(10)
    sock.close()

    turn = rows(
        settings,
        "SELECT fallback_used, trace_id FROM turns WHERE conversation_id = ?",
        cid,
    )[0]
    logged = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    warnings = [x for x in logged if x.get("level") == "warning"]
    print(
        f"\nreply={reply['text']!r} banner={reply['banner']} fallback_used={turn['fallback_used']} "
        f"trace_id={turn['trace_id']} warnings={warnings}"
    )
    assert reply["text"] == "Hello! How can I help?" and reply["banner"] == "none"
    assert turn["fallback_used"] == 0 and turn["trace_id"] is None
    assert [w["event"] for w in warnings] == ["trace_send_failed"]


class Exploding(RecordingTracer):
    def send(self, trace, on_sent):
        raise RuntimeError("tracer broke")


def test_tracer_that_raises_never_breaks_a_turn(started: Settings, capsys):
    client, _ = traced(started, [result(assistant("Hi."))], tracer=Exploding())
    cid = new_conversation(client)
    reply = say(client, cid, "hello")
    turn = rows(
        started,
        "SELECT fallback_used, trace_id FROM turns WHERE conversation_id = ?",
        cid,
    )[0]
    logged = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert (
        reply["text"] == "Hi."
        and turn["fallback_used"] == 0
        and turn["trace_id"] is None
    )
    assert [x["event"] for x in logged if x.get("level") == "warning"] == [
        "trace_send_failed"
    ]


def test_no_tracer_means_no_trace_id(started: Settings, capsys):
    client = TestClient(
        create_app(
            started,
            model=FakeModelProvider(results=[result(assistant("Hi."))]),
            clock=FakeClock(),
        )
    )
    cid = new_conversation(client)
    assert say(client, cid, "hello")["text"] == "Hi."
    turn = rows(started, "SELECT trace_id FROM turns WHERE conversation_id = ?", cid)[0]
    assert turn["trace_id"] is None
    assert "warning" not in capsys.readouterr().out
