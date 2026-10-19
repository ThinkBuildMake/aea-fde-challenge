"""S49 gate: every other handoff through the real Safety, Conversation, Knowledge,
Scheduling and Follow-ups, with only the network edges scripted (AZ-3, RL-3, criterion 10).
"""

import json
import re
import sqlite3
from typing import Any

import pytest

from app.conversation import guards
from app.llm import FakeModelProvider
from app.settings import Settings
from tests.gate.test_handoff_seams import (
    RECORDED,
    real_app,
    recording,
    rows,
    send,
    state_of,
)


def handoff(settings: Settings, cid: str) -> dict[str, Any]:
    found = rows(
        settings,
        "SELECT kind, reason, told_caller FROM handoffs WHERE conversation_id = ?",
        cid,
    )
    return dict(found[0]) if found else {}


def scheduling_counts(settings: Settings) -> tuple[int, int]:
    conn = sqlite3.connect(settings.SCHEDULING_DB_PATH)
    try:
        visits = conn.execute("SELECT COUNT(*) FROM appointments").fetchone()[0]
        open_slots = conn.execute(
            "SELECT COUNT(*) FROM appointment_slots WHERE status = 'open'"
        ).fetchone()[0]
    finally:
        conn.close()
    return visits, open_slots


def play(
    settings: Settings, name: str
) -> tuple[dict[str, Any], str, FakeModelProvider]:
    """Send a recording's question in a new conversation through the real app."""
    model = FakeModelProvider(results=recording(name))
    client = real_app(settings, model)
    question = json.loads((RECORDED / f"{name}.json").read_text())["question"]
    cid = client.post("/conversations").json()["conversationId"]
    reply = send(client, cid, question)
    row = handoff(settings, cid)
    print(f"\n[{name}] Q: {question}\nA: {reply['text']}")
    print(f"status={reply['status']} handoff={row.get('kind')}/{row.get('reason')}")
    return reply, cid, model


def tool_result(model: FakeModelProvider, name: str) -> dict[str, Any]:
    """The last result the model saw for a tool call whose id names `name`."""
    found = [
        json.loads(m["content"])
        for m in model.received[-1]
        if m.get("role") == "tool" and name in m["tool_call_id"]
    ]
    return found[-1]


def test_late_technician(kb_settings: Settings):
    reply, cid, model = play(kb_settings, "late_technician")
    assert reply["text"] == guards.TECHNICIAN_LATE_TEXT
    assert "waive" not in reply["text"].lower()
    assert len(model.received) == 1
    assert handoff(kb_settings, cid)["reason"] == "technician_late"
    assert state_of(kb_settings, cid) == {
        "handoffs": 1,
        "outcome": "handoff",
        "turns": 1,
    }


def test_daniel_north_plumbing(kb_settings: Settings):
    before = scheduling_counts(kb_settings)
    reply, cid, model = play(kb_settings, "north_plumbing")
    after = scheduling_counts(kb_settings)
    found = tool_result(model, "find_open_windows")
    print(f"find_open_windows reason={found['reason']} windows={found['windows']}")
    print(f"appointments, open slots before={before} after={after}")
    assert (found["reason"], found["windows"]) == ("no_plumber_in_zone", [])
    assert reply["text"] == guards.NO_PLUMBER_TEXT
    assert reply["booking"] is None and after == before
    assert handoff(kb_settings, cid)["reason"] == "no_plumber_in_zone"
    assert reply["status"] == "handed_off"


def test_geothermal_not_sure(kb_settings: Settings):
    reply, cid, _ = play(kb_settings, "geothermal")
    assert reply["text"].startswith(guards.NOT_SURE_LEAD)
    assert "$" not in reply["text"]
    assert handoff(kb_settings, cid)["reason"] == "no_document_answer"
    assert state_of(kb_settings, cid)["outcome"] == "handoff"


def test_unanswerable_invents_nothing(kb_settings: Settings):
    reply, cid, _ = play(kb_settings, "geothermal_invented")
    assert reply["text"] == f"{guards.NOT_SURE_LEAD} {guards.HANDOFF_TEXT}"
    assert "$12,000" not in reply["text"]
    row = handoff(kb_settings, cid)
    assert (row["reason"], row["told_caller"]) == ("no_document_answer", reply["text"])


def test_new_system_range(kb_settings: Settings):
    before = scheduling_counts(kb_settings)
    reply, cid, model = play(kb_settings, "new_system")
    passages = tool_result(model, "search_knowledge")["passages"]
    print("retrieved:", [(p["source"], p["section"]) for p in passages])
    assert any("$8,000" in p["text"] and "$16,000" in p["text"] for p in passages)
    assert "$8,000" in reply["text"] and "$16,000" in reply["text"]
    assert "free in-home estimate on site" in reply["text"]
    assert reply["booking"] is None and scheduling_counts(kb_settings) == before
    assert (reply["status"], handoff(kb_settings, cid)["reason"]) == (
        "handed_off",
        "new_system_quote",
    )


@pytest.mark.parametrize(
    ("name", "expected", "forbidden"),
    [
        ("late_technician", guards.TECHNICIAN_LATE_TEXT, "waive"),
        ("refund_demand", guards.SUPERVISOR_TEXT, "refund you"),
        ("new_system_firm", guards.HANDOFF_TEXT, "$9,500"),
    ],
)
def test_no_waiver_refund_or_firm_price(
    kb_settings: Settings, name: str, expected: str, forbidden: str
):
    reply, cid, _ = play(kb_settings, name)
    assert reply["text"] == expected
    assert forbidden not in reply["text"]
    assert state_of(kb_settings, cid)["handoffs"] == 1


def test_overview_counts_handled_topic_handoffs(kb_settings: Settings):
    for name in ("manor_heater", "north_plumbing", "refund_demand"):
        play(kb_settings, name)
    client = real_app(kb_settings, FakeModelProvider(results=[]))
    overview = client.get("/overview", headers={"Accept": "application/json"}).json()
    supporting = overview["supporting"]
    html = client.get("/business").text
    block = re.search(
        r'data-block="handoffs-handled-topics".*?</div></div>', html, re.DOTALL
    )
    assert block is not None
    shown = re.sub(r"<[^>]+>", " ", block.group())
    print(
        f"handoffsOnHandledTopicsPct={supporting['handoffsOnHandledTopicsPct']} "
        f"topHandoffReason={supporting['topHandoffReason']}\n"
        f"Overview block: {' '.join(shown.split())}"
    )
    assert supporting["handoffsOnHandledTopicsPct"] > 0
    assert supporting["topHandoffReason"] in {
        "city_not_in_zone_map",
        "no_plumber_in_zone",
    }
    assert re.search(r"Top reason: (city not in zone map|no plumber in zone)\.", shown)
    assert "_" not in shown
