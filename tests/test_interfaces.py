import inspect

import pytest

from app.conversation import service as conversation
from app.followups import service as followups
from app.knowledge import service as knowledge
from app.safety import service as safety
from app.scheduling import service as scheduling

FUNCTIONS = [
    (conversation.close_idle_conversations, ["ctx", "now"]),
    (conversation.end_with_handoff, ["tx", "conversation_id"]),
    (safety.redact_card_numbers, ["text"]),
    (safety.screen_safety, ["ctx", "text", "recent_turns", "follow_up_pending"]),
    (knowledge.search_knowledge, ["ctx", "query", "k"]),
    (knowledge.get_fee, ["ctx", "code"]),
    (knowledge.index_status, ["ctx"]),
    (knowledge.rebuild_index, ["ctx"]),
    (
        scheduling.identify_customer,
        ["ctx", "name", "phone", "account_number", "service_address"],
    ),
    (
        scheduling.find_open_windows,
        ["ctx", "customer_id", "service_type", "preferred_date", "preferred_window"],
    ),
    (scheduling.list_appointments, ["ctx", "customer_id"]),
    (scheduling.get_appointment, ["ctx", "customer_id", "appointment_id"]),
    (
        scheduling.book_visit,
        ["ctx", "customer_id", "slot_id", "issue", "conversation_id"],
    ),
    (scheduling.move_visit, ["ctx", "customer_id", "appointment_id", "new_slot_id"]),
    (scheduling.cancel_visit, ["ctx", "customer_id", "appointment_id"]),
    (scheduling.get_billing, ["ctx", "customer_id"]),
    (scheduling.create_payment_link, ["ctx", "customer_id", "invoice_id"]),
    (scheduling.reset_scheduling, ["ctx"]),
    (scheduling.scheduling_status, ["ctx"]),
    (followups.create_handoff, ["tx", "record", "ctx"]),
    (followups.set_callback_window, ["ctx", "conversation_id", "window"]),
    (followups.join_waitlist, ["ctx", "entry"]),
]

EXCEPTIONS = [
    safety.ScreenUnavailable,
    knowledge.IndexUnavailable,
    knowledge.EmbeddingUnavailable,
    knowledge.UnknownFee,
    scheduling.SchedulingUnavailable,
    scheduling.SlotUnavailable,
    scheduling.NotEligible,
    scheduling.AppointmentNotFound,
    scheduling.InvoiceNotFound,
    scheduling.NothingOwed,
    followups.NoHandoff,
]


@pytest.mark.parametrize(
    ("function", "names"), FUNCTIONS, ids=[f.__name__ for f, _ in FUNCTIONS]
)
def test_interface_has_documented_parameters(function, names):
    assert list(inspect.signature(function).parameters) == names


@pytest.mark.parametrize("error", EXCEPTIONS, ids=[e.__name__ for e in EXCEPTIONS])
def test_interface_exception_exists(error):
    assert issubclass(error, Exception)
