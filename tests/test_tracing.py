import json
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from pydantic import SecretStr

from app.conversation import tracing
from app.conversation.tracing import LangfuseTracer, Observation, TurnTrace
from app.settings import Settings

T0 = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
SECRET_CONVERSATION_ID = str(uuid.UUID(int=0xB6C2E4F1A2B))
CARD = "4111 1111 1111 1111"


def at(ms: int) -> datetime:
    return T0 + timedelta(milliseconds=ms)


def sample(session_id: str = "pub-session") -> TurnTrace:
    return TurnTrace(
        session_id=session_id,
        name="turn",
        start=at(0),
        end=at(900),
        input=f"card {CARD} for {SECRET_CONVERSATION_ID}",
        output="It is $89.",
        metadata={"seq": 1, "tools": ["search_knowledge"], "note": f"x {CARD}"},
        observations=[
            Observation(
                "safety_screen",
                "generation",
                at(1),
                at(200),
                model="safety-model",
                input_tokens=120,
                output_tokens=8,
                cost_usd=0.00002,
            ),
            Observation(
                "model_call",
                "generation",
                at(2),
                at(500),
                model="agent-model",
                input_tokens=100,
                output_tokens=20,
                cost_usd=0.1 + 0.2,
            ),
            Observation(
                "search_knowledge",
                "tool",
                at(510),
                at(600),
                model="embed-model",
                input_tokens=5,
                cost_usd=0.0000001,
                level="ERROR",
                status=f"ValueError: {CARD}",
                metadata={"ok": False, "error": f"bad {SECRET_CONVERSATION_ID}"},
            ),
        ],
    )


def exported(exporter: SpanExporter) -> tuple[LangfuseTracer, list[str]]:
    sent: list[str] = []
    tracer = LangfuseTracer(
        "http://127.0.0.1:9", "test-public", "test-secret", exporter=exporter
    )
    tracer.send(sample(), sent.append)
    tracer.flush(5)
    return tracer, sent


def test_scrub_masks_digit_runs_and_keeps_session_id():
    trace = sample(session_id="a1234567890123456b")
    clean = tracing.scrub(trace, SECRET_CONVERSATION_ID)
    text = json.dumps(
        [clean.input, clean.metadata, [o.status for o in clean.observations]],
        default=str,
    )
    assert CARD not in text and "[digits removed]" in text
    assert (
        SECRET_CONVERSATION_ID
        not in json.dumps([o.metadata for o in clean.observations]) + clean.input
    )
    assert clean.session_id == "a1234567890123456b"
    assert clean.observations[1].cost_usd == 0.3


def test_langfuse_tracer_maps_trace_to_otel_spans():
    memory = InMemorySpanExporter()
    _, sent = exported(memory)
    spans = {s.name: s for s in memory.get_finished_spans()}
    assert set(spans) == {"turn", "safety_screen", "model_call", "search_knowledge"}
    assert len({s.context.trace_id for s in spans.values()}) == 1
    assert all(s.attributes["session.id"] == "pub-session" for s in spans.values())
    root = spans["turn"]
    assert root.attributes["langfuse.trace.name"] == "turn"
    assert sent == [f"{root.context.trace_id:032x}"]
    screen = spans["safety_screen"].attributes
    assert spans["safety_screen"].start_time == int(at(1).timestamp() * 1e9)
    assert spans["safety_screen"].end_time == int(at(200).timestamp() * 1e9)
    assert screen["langfuse.observation.type"] == "generation"
    assert screen["langfuse.observation.model.name"] == "safety-model"
    assert json.loads(screen["langfuse.observation.usage_details"]) == {
        "input": 120,
        "output": 8,
    }
    assert json.loads(screen["langfuse.observation.cost_details"]) == {"total": 0.00002}
    search = spans["search_knowledge"].attributes
    assert search["langfuse.observation.type"] == "tool"
    assert json.loads(search["langfuse.observation.usage_details"]) == {"input": 5}
    assert search["langfuse.observation.level"] == "ERROR"
    assert all(
        s.parent.span_id == root.context.span_id
        for n, s in spans.items()
        if n != "turn"
    )


def test_otel_spans_never_carry_secret_id():
    memory = InMemorySpanExporter()
    tracer = LangfuseTracer(
        "http://127.0.0.1:9", "test-public", "test-secret", exporter=memory
    )
    tracing.send_turn_trace(tracer, sample(), SECRET_CONVERSATION_ID, lambda _id: None)
    tracer.flush(5)
    values = [
        str(v) for s in memory.get_finished_spans() for v in s.attributes.values()
    ]
    assert values and not any(SECRET_CONVERSATION_ID in v for v in values)


class Failing(SpanExporter):
    def __init__(self, raise_it: bool) -> None:
        self.raise_it = raise_it

    def export(self, spans):
        if self.raise_it:
            raise ConnectionError("down")
        return SpanExportResult.FAILURE


@pytest.mark.parametrize("raise_it", [False, True])
def test_failed_export_logs_one_warning_and_skips_on_sent(capsys, raise_it: bool):
    _, sent = exported(Failing(raise_it))
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert sent == []
    assert [(x["event"], x["level"]) for x in lines] == [
        ("trace_send_failed", "warning")
    ]


def test_tracer_for_is_off_without_keys(tmp_settings: Settings):
    assert tracing.tracer_for(tmp_settings) is None
    keyed = tmp_settings.model_copy(
        update={
            "LANGFUSE_PUBLIC_KEY": SecretStr("test-public"),
            "LANGFUSE_SECRET_KEY": SecretStr("test-secret"),
        }
    )
    assert isinstance(tracing.tracer_for(keyed), LangfuseTracer)


def test_gate_env_has_no_langfuse_keys():
    assert not {"LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"} & set(os.environ)


def test_flush_drops_sends_still_queued_after_its_wait():
    import threading
    import time

    class Slow(SpanExporter):
        def __init__(self) -> None:
            self.release = threading.Event()
            self.calls = 0

        def export(self, spans):
            self.calls += 1
            self.release.wait(timeout=10)
            return SpanExportResult.SUCCESS

    exporter = Slow()
    tracer = LangfuseTracer(
        "http://127.0.0.1:9", "test-public", "test-secret", exporter=exporter
    )
    for _ in range(4):
        tracer.send(sample(), lambda _id: None)
    tracer.flush(0.1)
    exporter.release.set()
    time.sleep(0.3)
    assert exporter.calls == 1
