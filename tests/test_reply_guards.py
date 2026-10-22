"""The reply rules as pure checks (VR-8, VR-9, AZ-3)."""

import json

import pytest

from app.conversation import guards
from app.types import Booking

BOOKING = Booking(
    appointment_id=1,
    slot_id=56,
    date="2026-10-19",
    window="08:00-12:00",
    technician_name="Marta Kowalski",
    service_type="hvac_repair",
    zone="north",
    diagnostic_fee_cents=8900,
    diagnostic_fee_waived=False,
)


@pytest.mark.parametrize(
    "text, mismatch",
    [
        ("booked Tuesday with Ray", True),
        ("Booked Tuesday", True),
        ("Booked October 21", True),
        ("Booked 21 October", True),
        ("Booked 2026-10-21", True),
        ("Booked 10/21", True),
        ("Booked at 9 AM", True),
        ("Booked at 1 PM", True),
        ("Booked with Ray", True),
        ("Booked Monday", False),
        ("Booked October 19", False),
        ("Booked Monday October 19, 8 AM to 12 PM with Marta.", False),
        ("Booked 8:00-12:00", False),
        ("Booked with Marta Kowalski", False),
        ("Booked with the technician", False),
        ("answer 0", False),
        (guards.confirmation_text(BOOKING), False),
    ],
)
def test_confirmation_mismatch(text: str, mismatch: bool):
    assert guards.confirmation_mismatch(text, BOOKING) is mismatch


def tool(content: object) -> dict:
    return {
        "role": "tool",
        "content": content if isinstance(content, str) else json.dumps(content),
    }


@pytest.mark.parametrize(
    "text, sources, unsupported",
    [
        ("$89", [tool({"passages": [{"text": "The fee is $89."}]})], []),
        ("$89", [tool({"passages": [{"text": "FEE-DIAG,Diagnostic,Fee,89,89"}]})], []),
        ("$89.00", [tool({"t": "$89"})], []),
        ("$1,200", [tool({"t": "1200"})], []),
        ("$89", [tool({"booking": {"diagnosticFeeCents": 8900}})], []),
        ("$49", [tool({"x": {"lateFeeCents": 4900}})], []),
        ("$120.50", [tool({"balanceCents": 12050})], []),
        ("$79", [tool({"t": "$89"})], ["$79"]),
        ("$4,200", [], ["$4,200"]),
        ("$1.2k", [tool({"t": "1.2"})], ["$1.2k"]),
        ("$1.2k", [tool({"t": "1200"})], []),
        ("$5K", [tool({"t": "5"})], ["$5K"]),
        ("$89", [{"role": "assistant", "content": "$89"}], ["$89"]),
    ],
)
def test_unsupported_figures(text: str, sources: list, unsupported: list[str]):
    assert guards.unsupported_figures(text, sources) == unsupported


@pytest.mark.parametrize(
    "text, promise",
    [
        ("We'll refund you today", True),
        ("I will waive the $49 fee", True),
        ("I'm going to credit your account", True),
        ("Someone will call you back today", True),
        ("We will call you back in two days", True),
        ("A person will call you back within 48 hours", True),
        ("I can't waive the fee", False),
        ("I cannot refund that", False),
        ("We won't refund", False),
        ("The diagnostic fee is waived for members", False),
        ("A supervisor will call you back within 1 business day", False),
        ("The team will call you if one opens.", False),
        (
            (
                "The diagnostic visit is $89, and we'll credit it toward the repair "
                "if you approve it during the same visit."
            ),
            False,
        ),
        ("We'll credit it toward the repair if you approve it", False),
        ("Unfortunately we will not refund the diagnostic fee.", False),
        ("We will never waive that fee.", False),
        ("A refund will be issued to your card today.", True),
        ("You'll be refunded in full.", True),
        ("I've gone ahead and refunded the $89.", True),
        ("Someone will call you back within 2 days.", True),
        ("We will call you back in 2 business days.", True),
        ("Would you like a callback today?", False),
        ("We'll refund you today, okay?", True),
        ("I'll call you back within 1 business day.", False),
        ("No refund will be issued for that visit.", False),
        ("I can take a credit card over the phone.", False),
        (
            (
                "I've logged your refund request, and a supervisor will call you "
                "within 1 business day."
            ),
            False,
        ),
        (
            (
                "I'll pass your refund request to a supervisor, who will call you "
                "within 1 business day."
            ),
            False,
        ),
        ("I've escalated your refund request.", False),
        ("We'll review your refund request.", False),
        ("I've opened a refund case for you.", False),
        ("We'll look at your refund claim.", False),
        ("I can explain our refund policy.", False),
        ("I'll note your refund question.", False),
        ("We'll issue you a full refund.", True),
        ("You will get a refund.", True),
        ("You'll receive a refund within 5 business days.", True),
        ("We'll call you tomorrow.", True),
        ("We'll call you back by end of day.", True),
        ("We'll call you when the technician is on the way today.", False),
        ("The team will call you on Friday.", True),
        ("We will call you at 3 PM.", True),
        ("The team will call you October 22.", True),
        ("The team will call you on 2026-10-22.", True),
        ("We will reach out to you on Monday.", True),
        ("You can call back Monday through Friday, 7 AM to 7 PM.", False),
        ("Feel free to reach out Monday to Friday 8 AM to 6 PM.", False),
        (
            "Feel free to reach out Monday to Friday 8 AM to 6 PM, or Saturday 9 AM to 1 PM.",
            False,
        ),
        ("You can reach out 24/7 at the emergency line.", False),
        ("For emergencies you can reach out 24/7 at the emergency line.", False),
        ("If you want a callback, the office handles them Monday to Friday.", False),
        ("If an earlier window opens, the team will call you.", False),
        (
            (
                "You are booked for Wednesday October 21, 1 PM to 5 PM with Jun Park, "
                "and the team will call you if an earlier one opens."
            ),
            False,
        ),
        (
            (
                "The earliest window is Wednesday October 21, 1 PM to 5 PM. If an "
                "earlier one opens, the team will call you."
            ),
            False,
        ),
    ],
)
def test_promises(text: str, promise: bool):
    assert guards.makes_promise(text) is promise


@pytest.mark.parametrize(
    "text",
    [
        guards.CARD_REFUSAL_TEXT,
        "Sorry, I can't accept card numbers here.",
        "I’m unable to take card details in this chat.",
        "For your security I do not store or process card numbers.",
        "We cannot process payments by card number in chat.",
    ],
)
def test_refuses_card(text: str):
    assert guards.refuses_card(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "Thanks, your card is noted.",
        "Your balance is $478.00. I cannot waive it. Your card was charged.",
        "You can pay with a card using the link.",
        "",
    ],
)
def test_does_not_count_as_card_refusal(text: str):
    assert guards.refuses_card(text) is False


def test_no_match_handoff_text():
    assert guards.handoff_text("no_account_match", "handoff") == guards.NO_MATCH_TEXT
    assert "could not find an account" in guards.NO_MATCH_TEXT
    assert "$" not in guards.NO_MATCH_TEXT


def test_payment_link_text():
    from app.types import PaymentLink

    link = PaymentLink(
        url="https://pay.example.com/invoice/INV-1?token=a", valid_for_hours=24
    )
    assert guards.payment_link_text(link) == (
        "You can pay securely with this link, valid for 24 hours: "
        "https://pay.example.com/invoice/INV-1?token=a"
    )


@pytest.mark.parametrize(
    ("text", "claims"),
    [
        ("I've cancelled your appointment for Saturday.", True),
        ("Your visit has been cancelled. A $49 fee was applied.", True),
        ("Done, it's canceled.", True),
        ("Your visit is not cancelled yet. Do you want me to cancel it?", False),
        ("Would you like it cancelled?", False),
        ("There is no fee to cancel. Do you want me to cancel it?", False),
        ("Nothing has been cancelled.", False),
        ("Auto-renew can be cancelled any time before your renewal date.", False),
        ("Your visit is cancelled.", True),
    ],
)
def test_claims_cancelled(text: str, claims: bool):
    assert guards.claims_cancelled(text) is claims
