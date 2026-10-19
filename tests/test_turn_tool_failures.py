"""A failing screen, search or scheduling call ends the turn with a fixed, caller-safe reply."""

import re
import time
from typing import Any

import pytest

from app.context import SystemClock
from app.conversation import guards
from app.followups.service import create_handoff
from app.knowledge.service import EmbeddingUnavailable, IndexUnavailable
from app.llm import FakeModelProvider
from app.safety.service import ScreenUnavailable
from app.scheduling.service import SchedulingUnavailable
from app.settings import Settings
from tests.test_turn import (
    assistant,
    client_for,
    new_conversation,
    result,
    say,
    tool_call,
)
from tests.test_turn_failures import turn_row
from tests.test_turn_guards import (
    Calls,
    book_call,
    calls,  # noqa: F401
    last_tool_result,
    match,
    windows_call,
)


def raise_with(exc: Exception):
    def boom(*args: Any, **kwargs: Any) -> Any:
        raise exc

    return boom


def show(reply: dict, turn: Any) -> None:
    print(
        f"text={reply['text']!r} choices={reply['choices']} booking={reply['booking']} "
        f"banner={reply['banner']} actions={reply['actions']} | "
        f"safety_verdict={turn['safety_verdict']} error={turn['error']} "
        f"fallback_used={turn['fallback_used']} offered={turn['offered']} "
        f"has_write={turn['has_write']} retrieved={turn['retrieved']} "
        f"latency_ms={turn['latency_ms']}"
    )


def test_a_failed_screen_offers_nothing(
    started: Settings,
    calls: Calls,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "app.safety.service.screen_safety",
        raise_with(ScreenUnavailable("screen down")),
    )
    model = FakeModelProvider(
        results=[
            result(
                assistant(
                    calls=[
                        windows_call(),
                        book_call(56, "yes").message["tool_calls"][0],
                    ]
                )
            ),
            result(assistant("Tuesday 8-10 is open.")),
        ]
    )
    client = client_for(started, model)
    cid = new_conversation(client)
    match(started, cid)
    reply = say(client, cid, "My AC is blowing warm air")
    turn = turn_row(started, cid)
    show(reply, turn)
    print(f"scheduling calls: windows={calls.windows} books={calls.books}")
    assert reply["text"] == guards.FALLBACK_TEXT
    assert reply["choices"] == [] and reply["booking"] is None
    assert "request_callback" in reply["actions"]
    assert turn["safety_verdict"] == "unscreened"
    assert turn["error"] == "screen_unavailable"
    assert turn["fallback_used"] == 1 and turn["offered"] == "{}"
    assert turn["has_write"] == 0
    assert calls.windows == [] and calls.books == []


@pytest.mark.parametrize(
    "exc", [EmbeddingUnavailable("down"), IndexUnavailable("none")]
)
def test_a_failed_search_answers_nothing_from_memory(
    started: Settings,
    calls: Calls,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    exc: Exception,
):
    monkeypatch.setattr("app.knowledge.service.search_knowledge", raise_with(exc))
    model = FakeModelProvider(
        results=[
            result(
                assistant(
                    calls=[tool_call("s", "search_knowledge", query="diagnostic fee")]
                )
            ),
            result(assistant("The diagnostic fee is $89.")),
        ]
    )
    client = client_for(started, model)
    cid = new_conversation(client)
    reply = say(client, cid, "What is the diagnostic fee?")
    turn = turn_row(started, cid)
    seen = last_tool_result(model)
    show(reply, turn)
    print(f"tool result the model saw: {seen}")
    assert "$" not in reply["text"] and not re.search(r"\d", reply["text"])
    assert reply["text"] == guards.NOT_SURE_TEXT
    assert "request_callback" in reply["actions"] and reply["banner"] == "none"
    assert turn["error"] == "embedding_unavailable"
    assert turn["fallback_used"] == 0 and turn["retrieved"] == "[]"
    assert seen == {
        "ok": False,
        "error": "embedding_unavailable",
        "instruction": guards.SEARCH_UNAVAILABLE_INSTRUCTION,
    }


def test_a_failed_booking_is_never_confirmed(
    started: Settings,
    calls: Calls,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("app.followups.service.create_handoff", create_handoff)
    calls.book_error = SchedulingUnavailable("scheduling database unavailable")
    model = FakeModelProvider(
        results=[
            result(assistant(calls=[windows_call()])),
            result(assistant("Tuesday 8-10 is open.")),
            book_call(56, "yes book it"),
            result(assistant("You are booked for Tuesday 8-10 with Dana.")),
        ]
    )
    client = client_for(started, model, SystemClock())
    cid = new_conversation(client)
    match(started, cid)
    say(client, cid, "I need a visit")
    t0 = time.monotonic()
    reply = say(client, cid, "yes book it")
    elapsed = time.monotonic() - t0
    turn = turn_row(started, cid, 2)
    show(reply, turn)
    print(f"answered in {elapsed:.2f}s; book_visit called with {calls.books}")
    assert calls.books == [56]
    assert reply["booking"] is None and reply["text"] == guards.FALLBACK_TEXT
    assert "booked" not in reply["text"]
    assert "request_callback" in reply["actions"]
    assert elapsed < 10 and turn["latency_ms"] < 10000
    assert turn["error"] == "scheduling_unavailable"
    assert turn["fallback_used"] == 1 and turn["has_write"] == 0
    resp = client.post(
        f"/conversations/{cid}/callback-window", json={"window": "morning"}
    )
    handoff = resp.json()["handoff"]
    print(
        f"callback-window -> {resp.status_code} reason={handoff['reason']} "
        f"byError={handoff.get('byError')}"
    )
    assert resp.status_code == 200
    assert handoff["reason"] == "scheduling_unavailable"
    assert handoff["byError"] is True


def test_de2_an_unreadable_schedule_never_confirms(
    started: Settings,
    calls: Calls,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "app.scheduling.service.find_open_windows",
        raise_with(SchedulingUnavailable("scheduling database unavailable")),
    )
    model = FakeModelProvider(
        results=[
            result(assistant(calls=[windows_call()])),
            result(assistant("You are booked for Tuesday.")),
        ]
    )
    client = client_for(started, model)
    cid = new_conversation(client)
    match(started, cid)
    reply = say(client, cid, "I need a visit")
    turn = turn_row(started, cid)
    show(reply, turn)
    assert reply["text"] == guards.FALLBACK_TEXT
    assert reply["booking"] is None and reply["choices"] == []
    assert "request_callback" in reply["actions"]
    assert turn["error"] == "scheduling_unavailable" and turn["fallback_used"] == 1
