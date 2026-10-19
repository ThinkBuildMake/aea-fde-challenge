"""S36 gate: billing through the real Conversation, Safety and privacy and Scheduling modules.

Only the network edges are scripted: the safety classifier's reply (stubbed here to record
what it was sent), the embedder (FakeEmbedder) and the agent model (hand-written
recordings in tests/gate/recorded/billing_*.json).
"""

import json
import re
import sqlite3
from typing import Any

import pytest

from app.conversation import guards
from app.llm import FakeModelProvider
from app.settings import Settings
from tests.gate.test_handoff_seams import real_app, recording, rows, send

CARDS = [
    "4111 1111 1111 1111",
    "4111    1111    1111    1111",
    "4111\n1111\n1111\n1111",
    "3782 822463 10005",
    "6011000990139424123",
]
# Any 13 or more digits, whatever whitespace, dots or hyphens sit between them.
DIGIT_RUN = re.compile(r"\d(?:[\s.\-]*\d){12,}")
BARE_RUN = re.compile(r"\d{13,19}")
LINDA = ["MHC-10001", "4412 Oak Hollow", "linda.foster@", "Round Rock"]


@pytest.fixture
def screened(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The real screen runs; its network call answers safe and records what it was sent."""
    from app.safety.service import OpenRouterSafetyClassifier

    sent: list[str] = []

    def classify(self: Any, messages: list[dict[str, Any]], timeout_s: float) -> str:
        sent.append(json.dumps(messages))
        return '{"verdict": "safe", "reason": "no_hazard"}'

    monkeypatch.setattr(OpenRouterSafetyClassifier, "classify", classify)
    return sent


def tool_outputs(settings: Settings, cid: str) -> list[dict[str, Any]]:
    out = []
    for turn in rows(
        settings,
        "SELECT model_messages FROM turns WHERE conversation_id = ? ORDER BY seq",
        cid,
    ):
        out += [
            json.loads(m["content"])
            for m in json.loads(turn["model_messages"])
            if m["role"] == "tool"
        ]
    return out


def customers(settings: Settings) -> int:
    conn = sqlite3.connect(settings.SCHEDULING_DB_PATH)
    try:
        return conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
    finally:
        conn.close()


def new(client: Any) -> str:
    return client.post("/conversations").json()["conversationId"]


def test_five_cards_and_a_payment_leave_no_digit_run(
    kb_settings: Settings, capfd: pytest.CaptureFixture[str], screened: list[str]
):
    client = real_app(
        kb_settings, FakeModelProvider(results=recording("billing_balance"))
    )
    cid = new(client)
    first = send(client, cid, "What do I owe? Omar Patel, account MHC-10002.")
    print(f"\nbalance: {first['text']}")
    for number in CARDS:
        reply = send(client, cid, f"My card is {number}.")
        print(f"card reply: status={reply['status']} text={reply['text']!r}")
        assert guards.refuses_card(reply["text"])
        assert "https://pay.example.com/invoice/INV-204411?token=" in reply["text"]
        assert (reply["status"], reply["banner"]) == ("active", "none")
    paid = send(client, cid, "I'd like to pay that now.")
    print(f"pay reply: {paid['text']!r}")
    assert "https://pay.example.com/invoice/INV-204411?token=" in paid["text"]

    turns = rows(kb_settings, "SELECT * FROM turns WHERE conversation_id = ?", cid)
    out = capfd.readouterr().out
    stored = [str(v) for t in turns for v in dict(t).values() if v is not None]
    found = [
        m.group()
        for text in [*stored, *out.splitlines(), *screened]
        for m in [DIGIT_RUN.search(text), BARE_RUN.search(text)]
        if m
    ]
    handoffs = rows(kb_settings, "SELECT COUNT(*) FROM handoffs")[0][0]
    print(
        f"turns={len(turns)} stored values={len(stored)} stdout lines="
        f"{len(out.splitlines())} screen inputs={len(screened)} "
        f"digit runs found={found} handoffs={handoffs}"
    )
    assert len(turns) == 7
    assert found == []
    assert handoffs == 0
    for number in ["4111111111111111", "4111 1111 1111 1111"]:
        assert not [t for t in [*stored, out, *screened] if number in t]


def test_link_for_another_customers_invoice_is_refused(kb_settings: Settings):
    client = real_app(
        kb_settings, FakeModelProvider(results=recording("billing_balance"))
    )
    cid = new(client)
    send(client, cid, "What do I owe? Omar Patel, account MHC-10002.")
    for number in CARDS:
        send(client, cid, f"My card is {number}.")
    send(client, cid, "I'd like to pay that now.")
    reply = send(client, cid, "Send me a payment link for INV-200111.")
    result = tool_outputs(kb_settings, cid)[-1]
    print(f"\ntool result: {result}\nreply: {reply['text']!r}")
    assert result["ok"] is False and result["error"].startswith("InvoiceNotFound")
    assert "INV-200111?token=" not in reply["text"]
    assert "pay.example.com" not in reply["text"]
    assert "965" not in json.dumps(tool_outputs(kb_settings, cid))


def test_mismatch_hands_off_and_adds_no_customer(kb_settings: Settings):
    before = customers(kb_settings)
    client = real_app(
        kb_settings, FakeModelProvider(results=recording("billing_mismatch"))
    )
    cid = new(client)
    reply = send(client, cid, "What's my balance? Omar Patel, 512-555-0101.")
    handoff = rows(
        kb_settings,
        "SELECT reason, customer_id FROM handoffs WHERE conversation_id = ?",
        cid,
    )
    after = customers(kb_settings)
    print(
        f"\nreply: {reply['text']!r}\nstatus={reply['status']} banner={reply['banner']}"
        f"\nhandoff={[dict(h) for h in handoff]} customers before={before} after={after}"
    )
    assert reply["text"] == guards.NO_MATCH_TEXT
    assert (reply["status"], reply["banner"]) == ("handed_off", "handoff")
    for word in ["$", "INV-", "Oak Hollow", "Brookside"]:
        assert word not in reply["text"]
    assert [dict(h) for h in handoff] == [
        {"reason": "no_account_match", "customer_id": None}
    ]
    assert after == before == 154


def test_neighbour_lookup_stays_on_the_callers_account(kb_settings: Settings):
    client = real_app(
        kb_settings, FakeModelProvider(results=recording("billing_neighbour"))
    )
    cid = new(client)
    send(client, cid, "Omar Patel, account MHC-10002.")
    reply = send(client, cid, "What does my neighbour Linda Foster owe?")
    results = tool_outputs(kb_settings, cid)
    customer = rows(kb_settings, "SELECT customer_id FROM conversations")[0][0]
    print(f"\nidentify result: {results[-2]}\nconversation customer={customer}")
    print(f"reply: {reply['text']!r}")
    assert results[-2]["error"] == "already_identified"
    assert customer == "MHC-10002"
    seen = json.dumps(results) + reply["text"]
    assert [w for w in LINDA if w in seen] == []


def test_new_conversation_starts_unidentified(kb_settings: Settings):
    client = real_app(
        kb_settings, FakeModelProvider(results=recording("billing_new_conversation"))
    )
    first = new(client)
    send(client, first, "Omar Patel, account MHC-10002.")
    second = new(client)
    reply = send(client, second, "What do I owe?")
    customer = rows(
        kb_settings, "SELECT customer_id FROM conversations WHERE id = ?", second
    )[0][0]
    billing = tool_outputs(kb_settings, second)[-1]
    print(f"\nnew conversation customer={customer} get_my_billing={billing}")
    print(f"reply: {reply['text']!r}")
    assert customer is None
    assert billing["error"] == "not_identified"
    assert "$" not in reply["text"]
