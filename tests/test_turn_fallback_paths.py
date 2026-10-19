"""S37: every failure path leaves a working call back that records the right reason."""

import json
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from app.context import SystemClock
from app.conversation import guards
from app.conversation.tracing import RecordingTracer
from app.followups import service as followups
from app.llm import FakeModelProvider
from app.main import create_app
from app.settings import Settings
from tests.gate.harness import FakeClock
from tests.test_turn import (
    assistant,
    client_for,
    new_conversation,
    result,
    rows,
    say,
    tool_call,
)
from tests.test_turn_guards import Calls, book_call, calls, offer_turn  # noqa: F401

REAL_CREATE_HANDOFF = followups.create_handoff


def test_failed_write_call_back_records_a_handoff(
    started: Settings,
    calls: Calls,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
):
    calls.book_error = RuntimeError("scheduling write failed")
    client, cid, _ = offer_turn(
        started,
        calls,
        [
            book_call(56, "yes book it"),
            result(assistant("Sorry, that did not go through.")),
        ],
    )
    reply = say(client, cid, "yes book it")
    error = rows(started, "SELECT error FROM turns WHERE seq = 2")[0][0]
    monkeypatch.setattr("app.followups.service.create_handoff", REAL_CREATE_HANDOFF)
    picked = client.post(
        f"/conversations/{cid}/callback-window", json={"window": "morning"}
    )
    row = rows(
        started,
        "SELECT reason, by_error, preferred_window FROM handoffs WHERE conversation_id = ?",
        cid,
    )
    outcome = rows(started, "SELECT outcome FROM conversations WHERE id = ?", cid)[0][0]
    print(
        f"\nactions={reply['actions']} turn error={error} pick={picked.status_code} "
        f"handoff={[dict(r) for r in row]} outcome={outcome}"
    )
    assert "request_callback" in reply["actions"] and error == "write_failed"
    assert picked.status_code == 200
    assert [dict(r) for r in row] == [
        {"reason": "write_failed", "by_error": 1, "preferred_window": "morning"}
    ]
    assert outcome == "handoff"


def test_abandoned_call_cost_is_added_late(started: Settings):
    settings = started.model_copy(update={"TURN_DEADLINE": 2})
    model = FakeModelProvider(
        results=[result(assistant("late"), cost=0.01)], delay_s=1.5
    )
    client = client_for(settings, model, SystemClock())
    cid = new_conversation(client)
    reply = say(client, cid, "hello")
    assert reply["text"] == guards.FALLBACK_TEXT
    cost = 0.0
    for _ in range(40):
        cost = rows(started, "SELECT cost_usd FROM conversations WHERE id = ?", cid)[0][
            0
        ]
        if cost:
            break
        time.sleep(0.1)
    print(f"\nfallback reply, then conversations.cost_usd={cost}")
    assert cost == pytest.approx(0.01)


def test_failed_save_seq_follows_the_last_row(started: Settings):
    client = client_for(started, FakeModelProvider(replies=["Hi there."]))
    cid = new_conversation(client)
    say(client, cid, "hello")
    conn = sqlite3.connect(started.APP_DB_PATH)
    conn.execute(
        "INSERT INTO turns (conversation_id, seq, kind, caller_text, reply_text, "
        "latency_ms) VALUES (?, 2, 'solved_answer', 'yes', '', 0)",
        (cid,),
    )
    conn.execute(
        "CREATE TRIGGER boom BEFORE INSERT ON turns "
        "BEGIN SELECT RAISE(ABORT, 'disk I/O error'); END"
    )
    conn.commit()
    conn.close()
    reply = say(client, cid, "again")
    print(
        f"\nfailed save after rows seq 1 (message), 2 (solved_answer): reply seq={reply['turn']['seq']}"
    )
    assert reply["turn"]["seq"] == 3


def test_failed_handoff_save_writes_a_fallback_turn(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    def failing(tx: sqlite3.Connection, conversation_id: str) -> None:
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr("app.conversation.service.end_with_handoff", failing)
    tracer = RecordingTracer()
    model = FakeModelProvider(
        results=[
            result(
                assistant(
                    calls=[tool_call("e", "escalate", reason="caller_asked_for_person")]
                )
            )
        ]
    )
    client = TestClient(
        create_app(started, model=model, clock=FakeClock(), tracer=tracer)
    )
    cid = new_conversation(client)
    reply = say(client, cid, "a person please")
    turn = rows(started, "SELECT * FROM turns WHERE conversation_id = ?", cid)
    meta = tracer.traces[-1].metadata
    print(
        f"\nreply={reply['text']!r} seq={reply['turn']['seq']} turns={len(turn)} "
        f"fallback_used={turn[0]['fallback_used']} error={turn[0]['error']} "
        f"trace fallback_used={meta['fallback_used']}"
    )
    assert reply["text"] == guards.FALLBACK_TEXT and reply["turn"]["seq"] == 1
    assert len(turn) == 1
    assert (turn[0]["fallback_used"], turn[0]["error"]) == (1, "handoff_save_failed")
    assert turn[0]["reply_text"] == guards.FALLBACK_TEXT
    assert json.loads(turn[0]["tools_called"]) == []
    assert meta["fallback_used"] == 1 and meta["seq"] == 1


def test_tool_error_stores_only_the_type(
    started: Settings,
    calls: Calls,  # noqa: F811
):
    calls.book_error = sqlite3.OperationalError("unable to open /srv/data/x.sqlite")
    client, cid, model = offer_turn(
        started,
        calls,
        [
            book_call(56, "yes book it"),
            result(assistant("Sorry, that did not go through.")),
        ],
    )
    say(client, cid, "yes book it")
    entry = json.loads(
        rows(started, "SELECT tools_called FROM turns WHERE seq = 2")[0][0]
    )[0]
    sent = json.loads(
        [m for m in model.received[-1] if m["role"] == "tool"][-1]["content"]
    )
    print(f"\nstored error={entry['error']!r} model saw error={sent['error']!r}")
    assert entry["error"] == "OperationalError"
    assert sent["error"] == "OperationalError"
