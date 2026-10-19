"""S39 gate: the trace seam over a recorded conversation with a card number (CP-1, PF-1).

The real Conversation module runs a three-turn conversation; only the network edges are
scripted (the recorded model turn, FakeEmbedder) and traces go to an in-memory recorder.
"""

import dataclasses
import json
from collections.abc import Callable

from app.conversation.tracing import RecordingTracer, TurnTrace
from app.llm import FakeModelProvider
from app.settings import Settings
from tests.gate.harness import CaseResult, FakeClock, evaluate_pf1
from tests.gate.test_policy_answer import QUESTION, real_app, recorded, rows
from tests.test_turn import LONG_DIGITS, assistant, result

MESSAGES = [QUESTION, "My card is 4111 1111 1111 1111", "and 4111111111111111"]


class FailingRecorder(RecordingTracer):
    def send(self, trace: TurnTrace, on_sent: Callable[[str], None]) -> None:
        raise ConnectionError("recorder down")


def play(settings: Settings, recorder: RecordingTracer):
    model = FakeModelProvider(
        results=[
            *recorded(),
            result(assistant("Thanks, I can't take card numbers here.")),
            result(assistant("Please don't share card numbers in the chat.")),
        ]
    )
    clock = FakeClock()
    client, _ = real_app(settings, model, clock)
    client.app.state.ctx.tracer = recorder
    cid = client.post("/conversations").json()["conversationId"]
    replies, first = [], None
    for text in MESSAGES:
        started = clock.monotonic()
        response = client.post(f"/conversations/{cid}/messages", json={"text": text})
        first = first or CaseResult(
            "trace_seam", round((clock.monotonic() - started) * 1000)
        )
        replies.append((response.status_code, response.json()))
    return cid, replies, first


def message_turns(settings: Settings, cid: str):
    return rows(
        settings,
        "SELECT seq, trace_id, fallback_used FROM turns"
        " WHERE conversation_id = ? AND kind = 'message' ORDER BY seq",
        cid,
    )


def test_gate_each_turn_names_a_recorded_card_free_trace(kb_settings: Settings):
    recorder = RecordingTracer()

    cid, replies, _ = play(kb_settings, recorder)

    turns = message_turns(kb_settings, cid)
    (public_id,) = rows(
        kb_settings, "SELECT public_id FROM conversations WHERE id = ?", cid
    )[0]
    dumped = json.dumps(
        [{**dataclasses.asdict(t), "session_id": ""} for t in recorder.traces],
        default=str,
    )
    print(f"\nreplies: {[(code, body['banner']) for code, body in replies]}")
    print(f"turns.trace_id by seq: {[(t['seq'], t['trace_id']) for t in turns]}")
    print(f"recorded trace ids:    {recorder.ids}")
    print(
        f"trace session ids == public id: {[t.session_id == public_id for t in recorder.traces]}"
    )
    print(f"trace inputs: {[t.input for t in recorder.traces]}")
    print(f"13-19 digit runs in traces: {len(LONG_DIGITS.findall(dumped))}")
    assert [code for code, _ in replies] == [200, 200, 200]
    assert "$89" in replies[0][1]["text"]
    assert len(recorder.traces) == 3
    assert [t["trace_id"] for t in turns] == recorder.ids
    assert all(t.session_id == public_id for t in recorder.traces)
    assert [t.input for t in recorder.traces][1:] == [
        "My card is [card number removed]",
        "and [card number removed]",
    ]
    assert LONG_DIGITS.search(dumped) is None


def test_gate_failing_recorder_leaves_trace_id_empty(kb_settings: Settings):
    recorder = FailingRecorder()

    cid, replies, first = play(kb_settings, recorder)

    turns = message_turns(kb_settings, cid)
    verdict = evaluate_pf1([first])
    print(
        f"\nreplies: {[(code, body['banner'], body['text'][:40]) for code, body in replies]}"
    )
    print(f"turns (seq, trace_id, fallback_used): {[tuple(t) for t in turns]}")
    print(verdict.message)
    assert [code for code, _ in replies] == [200, 200, 200]
    assert all(body["banner"] == "none" and body["text"] for _, body in replies)
    assert "$89" in replies[0][1]["text"]
    assert [tuple(t) for t in turns] == [(1, None, 0), (2, None, 0), (3, None, 0)]
    assert recorder.traces == []
    assert verdict.passed
