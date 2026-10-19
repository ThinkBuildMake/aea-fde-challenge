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
from app.types import CancelResult, Verdict
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
    turn = turn_row(started, cid)
    print(
        f"hang: answered in {elapsed:.1f}s text={reply['text']!r} "
        f"text==FALLBACK_TEXT: {reply['text'] == guards.FALLBACK_TEXT} "
        f"banner={reply['banner']} actions={reply['actions']} "
        f"fallback_used={turn['fallback_used']} error={turn['error']}"
    )
    assert elapsed < 15
    assert_fallback(reply)
    assert reply["status"] == "active"
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
    print(
        f"{code}: text={reply['text']!r} text==FALLBACK_TEXT: "
        f"{reply['text'] == guards.FALLBACK_TEXT} status={reply['status']}"
    )
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
    conv = rows(started, "SELECT * FROM conversations WHERE id = ?", cid)[0]
    print(
        f"replay: status={reply['status']} text={reply['text']!r} "
        f"text==FALLBACK_TEXT: {reply['text'] == guards.FALLBACK_TEXT} "
        f"outcome={conv['outcome']} outcome_reason={conv['outcome_reason']}"
    )
    assert_fallback(reply)
    assert reply["status"] == "ended"
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
    assert turn_row(started, cid)["error"] == "provider_error"


def test_a_slow_screen_after_the_model_returns_takes_the_fallback(
    started: Settings,
    calls: Calls,  # noqa: F811
):
    calls.screen_gate = threading.Event()
    settings = started.model_copy(update={"TURN_DEADLINE": 3})
    client = client_for(settings, FakeModelProvider(replies=["Hi."]), SystemClock())
    cid = new_conversation(client)
    try:
        t0 = time.monotonic()
        reply = say(client, cid, "hello")
        elapsed = time.monotonic() - t0
    finally:
        calls.screen_gate.set()
    assert elapsed < 3
    assert_fallback(reply)
    turn = turn_row(started, cid)
    assert turn["fallback_used"] == 1 and turn["error"] == "provider_timeout"
    assert calls.windows == [] and calls.books == []


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


@pytest.fixture
def gas_screen(monkeypatch: pytest.MonkeyPatch) -> None:
    """The danger screen says gas; Follow-ups is the real module."""
    monkeypatch.setattr(
        "app.safety.service.screen_safety",
        lambda ctx, text, recent, pending: Verdict(verdict="emergency", reason="gas"),
    )


def _trigger(settings: Settings, table: str) -> None:
    conn = sqlite3.connect(settings.APP_DB_PATH)
    conn.execute(
        f"CREATE TRIGGER boom_{table} BEFORE INSERT ON {table} "
        "BEGIN SELECT RAISE(ABORT, 'disk I/O error'); END"
    )
    conn.commit()
    conn.close()


def test_a_failed_save_still_records_the_safety_handoff(
    started: Settings,
    gas_screen: None,
):
    client = client_for(started, FakeModelProvider(replies=["Hi."]))
    cid = new_conversation(client)
    _trigger(started, "turns")
    reply = say(client, cid, "I smell gas")
    handoffs = rows(started, "SELECT kind, reason, told_caller FROM handoffs")
    outcome = rows(started, "SELECT outcome FROM conversations")[0][0]
    print(f"reply status={reply['status']} handoffs={[tuple(h) for h in handoffs]}")
    print(f"turns={len(rows(started, 'SELECT * FROM turns'))} outcome={outcome}")
    assert reply["text"] == guards.emergency_text(matched=False)
    assert reply["status"] == "safety_stop"
    assert rows(started, "SELECT * FROM turns") == []
    assert [tuple(h) for h in handoffs] == [
        ("safety_stop", "gas", guards.emergency_text(matched=False))
    ]
    assert outcome == "safety_stop"


def test_a_lost_safety_handoff_is_logged(
    started: Settings,
    gas_screen: None,
    capsys: pytest.CaptureFixture[str],
):
    client = client_for(started, FakeModelProvider(replies=["Hi."]))
    cid = new_conversation(client)
    _trigger(started, "turns")
    _trigger(started, "handoffs")
    capsys.readouterr()
    reply = say(client, cid, "I smell gas")
    lines = [
        json.loads(x) for x in capsys.readouterr().out.splitlines() if x.startswith("{")
    ]
    lost = [x for x in lines if x["event"] == "safety_handoff_failed"]
    print(f"reply status={reply['status']} log={lost}")
    assert reply["text"] == guards.emergency_text(matched=False)
    assert len(lost) == 1 and lost[0]["level"] == "error"
    assert rows(started, "SELECT * FROM handoffs") == []


def test_a_matched_callers_safety_row_names_them(
    started: Settings,
    gas_screen: None,
):
    client = client_for(started, FakeModelProvider(replies=["Hi."]))
    cid = new_conversation(client)
    match(started, cid, "MHC-10001")
    say(client, cid, "I smell gas")
    conn = sqlite3.connect(started.SCHEDULING_DB_PATH)
    expected = conn.execute(
        "SELECT name, phone FROM customers WHERE customer_id = 'MHC-10001'"
    ).fetchone()
    conn.close()
    row = rows(started, "SELECT caller_name, caller_phone, kind FROM handoffs")[0]
    print(f"handoff caller={row['caller_name']} kind={row['kind']}")
    assert (row["caller_name"], row["caller_phone"]) == tuple(expected)
    assert row["kind"] == "safety_stop"
