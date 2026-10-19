"""Gate guards for S15: no card reaches a trace (CP-1); a hanging Langfuse never slows a reply (PF-1)."""

import dataclasses
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from app.conversation.tracing import LangfuseTracer, RecordingTracer, Tracer
from app.llm import FakeModelProvider
from app.main import create_app
from app.settings import Settings
from tests.gate.harness import FakeClock, evaluate_pf1, play_case
from tests.gate.test_first_reply import CASE
from tests.test_turn import LONG_DIGITS

CARDS = [
    "4111 1111 1111 1111",
    "4111-1111-1111-1111",
    "4111111111111111",
    "3782 822463 10005",
    "6011000990139424123",
]


def play(settings: Settings, tracer: Tracer, text: str) -> None:
    model = FakeModelProvider(replies=[f"Noted: {text}"])
    client = TestClient(
        create_app(settings, model=model, clock=FakeClock(), tracer=tracer)
    )
    cid = client.post("/conversations").json()["conversationId"]
    client.post(f"/conversations/{cid}/messages", json={"text": f"My card is {text}"})


@pytest.mark.parametrize("card", CARDS)
def test_gate_cp1_no_card_reaches_a_trace(started: Settings, card: str):
    recorder = RecordingTracer()
    exported = InMemorySpanExporter()
    langfuse = LangfuseTracer(
        "http://127.0.0.1:9", "test-public", "test-secret", exporter=exported
    )
    # The session id is the random hex public id, never caller text; it is left out.
    play(started, recorder, card)
    play(started, langfuse, card)
    langfuse.flush(5)

    recorded = json.dumps(
        [{**dataclasses.asdict(t), "session_id": ""} for t in recorder.traces],
        default=str,
    )
    spans = [
        str(v)
        for s in exported.get_finished_spans()
        for k, v in s.attributes.items()
        if k != "session.id"
    ]
    assert recorder.traces and spans
    assert LONG_DIGITS.search(recorded) is None
    assert not [v for v in spans if LONG_DIGITS.search(v)]


class Hanging(SpanExporter):
    def __init__(self) -> None:
        self.release = threading.Event()
        self.entered = threading.Event()

    def export(self, spans):
        self.entered.set()
        self.release.wait(timeout=30)
        return SpanExportResult.SUCCESS


def test_gate_pf1_holds_while_langfuse_hangs(started: Settings):
    exporter = Hanging()
    tracer = LangfuseTracer(
        "http://127.0.0.1:9", "test-public", "test-secret", exporter=exporter
    )
    clock = FakeClock()
    client = TestClient(
        create_app(started, model=FakeModelProvider(), clock=clock, tracer=tracer)
    )
    wall = time.monotonic()
    verdict = evaluate_pf1([play_case(client, CASE, clock)])
    elapsed = time.monotonic() - wall
    assert exporter.entered.wait(5)
    still_hanging = not exporter.release.is_set()
    exporter.release.set()
    tracer.flush(5)
    assert verdict.passed, verdict.message
    assert still_hanging and elapsed < 2.0
