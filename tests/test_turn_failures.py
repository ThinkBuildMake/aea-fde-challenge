"""A failing model, a refused replay or a failed save still gets the caller an answer in time."""

import json
import sqlite3
import threading
import time

import openai
import pytest

from app.context import SystemClock
from app.conversation import guards
from app.llm import FakeModelProvider, status_error
from app.settings import Settings
from app.types import CancelResult
from tests.test_turn import (
    assistant,
    client_for,
    new_conversation,
    result,
    rows,
    say,
    tool_call,
)
from tests.test_turn_guards import Calls, calls, match  # noqa: F401


def turn_row(settings: Settings, cid: str, seq: int = 1) -> sqlite3.Row:
    return rows(
        settings, "SELECT * FROM turns WHERE conversation_id = ? AND seq = ?", cid, seq
    )[0]


def assert_fallback(reply: dict) -> None:
    assert reply["text"] == guards.FALLBACK_TEXT
    assert reply["banner"] == "error"
    assert "request_callback" in reply["actions"]
    assert reply["booking"] is None and reply["choices"] == []


def test_a_hanging_model_still_answers_within_the_deadline(started: Settings):
    release = threading.Event()
    client = client_for(started, FakeModelProvider(hang=release), SystemClock())
    cid = new_conversation(client)
    try:
        t0 = time.monotonic()
        reply = say(client, cid, "hello")
        elapsed = time.monotonic() - t0
    finally:
        release.set()
    print(
        f"hang: answered in {elapsed:.1f}s banner={reply['banner']} actions={reply['actions']}"
    )
    assert elapsed < 15
    assert_fallback(reply)
    assert reply["status"] == "active"
    turn = turn_row(started, cid)
    assert turn["fallback_used"] == 1 and turn["error"] == "provider_timeout"
    assert turn["latency_ms"] < 15000


def test_a_provider_timeout_is_recorded(started: Settings):
    request = openai.APITimeoutError(request=None)  # type: ignore[arg-type]
    client = client_for(started, FakeModelProvider(fail_with=request))
    cid = new_conversation(client)
    assert_fallback(say(client, cid, "hello"))
    assert turn_row(started, cid)["error"] == "provider_timeout"


@pytest.mark.parametrize("code", [402, 429])
def test_provider_status_errors_get_the_fallback(started: Settings, code: int):
    model = FakeModelProvider(fail_with=status_error(code))
    client = client_for(started, model)
    cid = new_conversation(client)
    reply = say(client, cid, "hello")
    print(f"{code}: text={reply['text'][:30]!r} status={reply['status']}")
    assert_fallback(reply)
    assert reply["status"] == "active"
    turn = turn_row(started, cid)
    assert turn["error"] == "provider_error" and turn["fallback_used"] == 1
    assert rows(started, "SELECT outcome FROM conversations")[0][0] is None
    model.fail_with = None
    assert say(client, cid, "again")["banner"] == "none"


def test_a_rejected_replay_ends_the_conversation(started: Settings):
    client = client_for(started, FakeModelProvider(reject_replay=True))
    cid = new_conversation(client)
    assert say(client, cid, "hello")["banner"] == "none"
    reply = say(client, cid, "and again")
    print(f"replay: status={reply['status']} text={reply['text'][:20]!r}")
    assert_fallback(reply)
    assert reply["status"] == "ended"
    conv = rows(started, "SELECT * FROM conversations WHERE id = ?", cid)[0]
    assert conv["outcome"] == "failed" and conv["outcome_reason"] == "replay_rejected"
    assert conv["ended_at"]
    turn = turn_row(started, cid, 2)
    assert turn["error"] == "replay_rejected" and turn["fallback_used"] == 1
    again = client.post(f"/conversations/{cid}/messages", json={"text": "x"})
    assert again.status_code == 409 and again.json()["error"] == "conversation_ended"


def test_a_failed_turn_insert_still_returns_the_reply(
    started: Settings, capsys: pytest.CaptureFixture[str]
):
    client = client_for(started, FakeModelProvider(replies=["Hi there."]))
    cid = new_conversation(client)
    conn = sqlite3.connect(started.APP_DB_PATH)
    conn.execute(
        "CREATE TRIGGER boom BEFORE INSERT ON turns "
        "BEGIN SELECT RAISE(ABORT, 'disk I/O error'); END"
    )
    conn.commit()
    conn.close()
    capsys.readouterr()
    reply = say(client, cid, "hello")
    lines = [
        json.loads(x) for x in capsys.readouterr().out.splitlines() if x.startswith("{")
    ]
    failed = [x for x in lines if x["event"] == "turn_save_failed"]
    print(f"reply={reply['text']!r} log={failed}")
    assert reply["text"] == "Hi there."
    assert len(failed) == 1 and failed[0]["table"] == "turns"
    assert rows(started, "SELECT * FROM turns") == []
    assert rows(started, "SELECT turn_count FROM conversations")[0][0] == 0


def test_an_emergency_verdict_wins_over_a_provider_failure(
    started: Settings,
    calls: Calls,  # noqa: F811
):
    calls.verdicts = ["emergency"]
    client = client_for(started, FakeModelProvider(fail_with=status_error(402)))
    cid = new_conversation(client)
    reply = say(client, cid, "I smell gas")
    assert reply["text"] == guards.emergency_text(matched=False)
    assert reply["status"] == "safety_stop" and len(calls.handoffs) == 1


def test_a_committed_cancel_survives_a_failed_turn(
    started: Settings,
    calls: Calls,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
):
    def cancel(ctx, customer_id, appointment_id, conversation_id):
        calls.cancels.append(appointment_id)
        return CancelResult(
            appointment_id=appointment_id,
            freed_slot_id=56,
            late_fee_applies=False,
            hours_before=48.0,
        )

    monkeypatch.setattr("app.scheduling.service.cancel_visit", cancel)

    class Fails(FakeModelProvider):
        def complete(self, messages, *, tools=None, timeout_s):
            if self.results is not None and len(self.results) == 1:
                raise status_error(429)
            return super().complete(messages, tools=tools, timeout_s=timeout_s)

    cancel = result(
        assistant(
            calls=[
                tool_call(
                    "x",
                    "cancel_visit",
                    appointmentId=7,
                    callerQuote="cancel it",
                )
            ]
        )
    )
    client = client_for(started, Fails(results=[cancel, result(assistant("never"))]))
    cid = new_conversation(client)
    match(started, cid)
    conn = sqlite3.connect(started.APP_DB_PATH)
    conn.execute(
        "INSERT INTO turns (conversation_id, seq, kind, caller_text, reply_text, "
        "model_messages, tools_called, retrieved, latency_ms, cost_usd, cost_source, "
        "safety_verdict, offered, has_write) VALUES (?, 1, 'message', 'a', 'b', '[]', "
        "'[]', '[]', 1, 0, 'reported', 'safe', '{\"appointmentIds\": [7]}', 0)",
        (cid,),
    )
    conn.commit()
    conn.close()
    reply = say(client, cid, "cancel it")
    assert calls.cancels == [7]
    assert reply["text"] == guards.CANCELLED_TEXT and reply["banner"] == "none"
    turn = turn_row(started, cid, 2)
    assert turn["error"] == "provider_error" and turn["fallback_used"] == 0


def test_a_tool_call_without_an_id_gets_the_fallback(started: Settings):
    bad = tool_call("", "search_knowledge", query="fee")
    del bad["id"]
    client = client_for(
        started, FakeModelProvider(results=[result(assistant(calls=[bad]))])
    )
    cid = new_conversation(client)
    assert_fallback(say(client, cid, "hello"))
    assert turn_row(started, cid)["error"] == "malformed_reply"


def test_exhausted_tool_rounds_get_the_fallback(started: Settings):
    loop = result(assistant(calls=[tool_call("c", "search_knowledge", query="fee")]))
    client = client_for(started, FakeModelProvider(results=[loop]))
    cid = new_conversation(client)
    assert_fallback(say(client, cid, "hello"))
    assert turn_row(started, cid)["error"] == "tool_rounds_exhausted"


def test_an_empty_final_reply_gets_the_fallback(started: Settings):
    client = client_for(started, FakeModelProvider(results=[result(assistant(""))]))
    cid = new_conversation(client)
    assert_fallback(say(client, cid, "hello"))
    assert turn_row(started, cid)["error"] == "empty_reply"


def test_unreported_tokens_are_null(started: Settings):
    client = client_for(started, FakeModelProvider(fail_with=status_error(402)))
    cid = new_conversation(client)
    say(client, cid, "hello")
    turn = turn_row(started, cid)
    assert turn["prompt_tokens"] is None and turn["completion_tokens"] is None


def test_de1_no_provider_text_or_trace_reaches_the_caller(
    started: Settings, capsys: pytest.CaptureFixture[str]
):
    loop = result(assistant(calls=[tool_call("c", "search_knowledge", query="fee")]))
    noid = tool_call("n", "search_knowledge", query="fee")
    del noid["id"]
    models = [
        FakeModelProvider(fail_with=openai.APITimeoutError(request=None)),  # type: ignore[arg-type]
        FakeModelProvider(fail_with=status_error(402)),
        FakeModelProvider(fail_with=status_error(429)),
        FakeModelProvider(fail_with=RuntimeError("secret provider detail sk-or-xyz")),
        FakeModelProvider(results=[result(assistant(calls=[noid]))]),
        FakeModelProvider(results=[loop]),
    ]
    for model in models:
        client = client_for(started, model)
        cid = new_conversation(client)
        response = client.post(f"/conversations/{cid}/messages", json={"text": "hi"})
        assert response.status_code == 200
        assert_fallback(response.json())
        assert "secret provider detail" not in response.text
    out = capsys.readouterr().out
    assert "secret provider detail" not in out and "Traceback" not in out


def test_ob3_a_fallback_is_countable_apart_from_handoffs(started: Settings):
    model = FakeModelProvider(fail_with=status_error(402))
    client = client_for(started, model)
    cid = new_conversation(client)
    say(client, cid, "hello")
    first = turn_row(started, cid, 1)
    assert (first["fallback_used"], first["error"]) == (1, "provider_error")
    assert rows(started, "SELECT * FROM handoffs") == []
    assert rows(started, "SELECT outcome FROM conversations")[0][0] is None
    resp = client.post(
        f"/conversations/{cid}/callback-window", json={"window": "morning"}
    )
    print(resp.status_code, resp.text[:200])
    assert resp.status_code == 200
    handoff = rows(started, "SELECT * FROM handoffs")[0]
    assert handoff["by_error"] == 1 and handoff["reason"] == "provider_failure"
    model.fail_with = None
    say(client, new_conversation(client), "fine")
    ok = rows(started, "SELECT fallback_used, error FROM turns ORDER BY id")[-1]
    assert tuple(ok) == (0, None)
