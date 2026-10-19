"""A payment link always reaches the caller, and a card turn always refuses (S36 AC3, AC4)."""

import json
from typing import Any

import pytest

from app.conversation import guards
from app.llm import FakeModelProvider
from app.settings import Settings
from app.types import Billing, Invoice, LineItem, PaymentLink
from tests.test_agent_tools import customer, identify, stub
from tests.test_turn import (
    assistant,
    client_for,
    new_conversation,
    result,
    rows,
    say,
    tool_call,
)

URL = "https://pay.example.com/invoice/INV-204411?token=abc"
CARD = "My card is 4111 1111 1111 1111."


@pytest.fixture
def omar(monkeypatch: pytest.MonkeyPatch):
    stub(monkeypatch, "app.scheduling.service.identify_customer", customer("MHC-10002"))
    stub(
        monkeypatch,
        "app.scheduling.service.get_billing",
        Billing(
            balance_cents=47800,
            invoices=[
                Invoice(
                    invoice_id="INV-204411",
                    issued_date="2026-10-01",
                    due_date="2026-10-31",
                    amount_cents=47800,
                    balance_cents=47800,
                    line_items=[LineItem(desc="After-hours dispatch", cents=14400)],
                ),
                Invoice(
                    invoice_id="INV-100001",
                    issued_date="2026-01-01",
                    due_date="2026-01-31",
                    amount_cents=9000,
                    balance_cents=0,
                    line_items=[],
                ),
            ],
        ),
    )
    return stub(
        monkeypatch,
        "app.scheduling.service.create_payment_link",
        PaymentLink(url=URL, valid_for_hours=24),
    )


def converse(started: Settings, turns: list[tuple[str, list[Any], str]]):
    """One turn per (caller text, tool calls, final model text)."""
    results = []
    for _, calls, answer in turns:
        if calls:
            results.append(result(assistant(calls=calls)))
        results.append(result(assistant(answer)))
    client = client_for(started, FakeModelProvider(results=results))
    cid = new_conversation(client)
    return cid, [say(client, cid, text) for text, _, _ in turns]


def last_assistant(started: Settings, cid: str) -> str:
    stored = rows(
        started,
        "SELECT model_messages FROM turns WHERE conversation_id = ? ORDER BY seq DESC",
        cid,
    )[0]["model_messages"]
    return json.loads(stored)[-1]["content"]


def test_link_is_added_when_the_model_omits_it(started: Settings, omar):
    cid, replies = converse(
        started,
        [
            ("Omar Patel, 512-555-0102", identify("MHC-10002"), "Thanks Omar."),
            (
                "I'd like to pay that now.",
                [tool_call("p", "send_payment_link", invoiceId="INV-204411")],
                "I've sent a payment link for your invoice to your phone.",
            ),
        ],
    )
    text = replies[1]["text"]
    print(text)
    assert URL in text
    assert text.endswith(
        guards.payment_link_text(PaymentLink(url=URL, valid_for_hours=24))
    )
    assert URL in last_assistant(started, cid)


@pytest.mark.parametrize(
    "calls",
    [
        [],
        [
            tool_call(
                "e",
                "escalate",
                kind="supervisor_callback",
                reason="billing_dispute",
                intent="x",
                toldCaller="x",
            )
        ],
    ],
    ids=["no_tools", "escalate"],
)
def test_card_turn_refuses_and_offers_link(started: Settings, omar, calls):
    cid, replies = converse(
        started,
        [
            ("Omar Patel, 512-555-0102", identify("MHC-10002"), "Thanks Omar."),
            (CARD, calls, "Noted."),
        ],
    )
    reply = replies[1]
    print(reply["text"])
    assert reply["text"].startswith(guards.CARD_REFUSAL_TEXT)
    assert guards.refuses_card(reply["text"])
    assert URL in reply["text"]
    assert (reply["status"], reply["banner"]) == ("active", "none")
    assert rows(started, "SELECT * FROM handoffs WHERE conversation_id = ?", cid) == []
    assert [c[2] for c in omar.calls] == ["INV-204411"]
    stored = rows(started, "SELECT * FROM turns WHERE conversation_id = ?", cid)
    blob = json.dumps([dict(r) for r in stored])
    assert "4111" not in blob
    assert URL in last_assistant(started, cid)


def test_card_turn_unmatched_refuses_without_link(started: Settings, omar):
    _, replies = converse(started, [(CARD, [], "Noted.")])
    text = replies[0]["text"]
    assert text.startswith(guards.CARD_REFUSAL_TEXT)
    assert "pay.example.com" not in text
    assert omar.calls == []


def test_card_turn_already_refused_is_not_prefixed(started: Settings, omar):
    _, replies = converse(
        started,
        [
            ("Omar Patel, 512-555-0102", identify("MHC-10002"), "Thanks Omar."),
            (CARD, [], "Sorry, I can't accept card numbers here."),
        ],
    )
    text = replies[1]["text"]
    assert text.startswith("Sorry, I can't accept card numbers here.")
    assert guards.CARD_REFUSAL_TEXT not in text
    assert URL in text


def test_card_turn_reuses_a_link_the_reply_already_holds(started: Settings, omar):
    _, replies = converse(
        started,
        [
            ("Omar Patel, 512-555-0102", identify("MHC-10002"), "Thanks Omar."),
            (
                "I'd like to pay that now.",
                [tool_call("p", "send_payment_link", invoiceId="INV-204411")],
                f"Here is your link: {URL}",
            ),
            (CARD, [], f"I can't accept card numbers here. Please use {URL}"),
        ],
    )
    text = replies[2]["text"]
    assert text.count(URL) == 1
    assert len(omar.calls) == 1
