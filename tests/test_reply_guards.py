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
    ],
)
def test_promises(text: str, promise: bool):
    assert guards.makes_promise(text) is promise
