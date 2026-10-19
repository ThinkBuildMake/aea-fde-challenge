"""Shared types (ARCHITECTURE: Shared types, Overview) and each route's request/response shape."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class Model(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


Zone = Literal["north", "central", "south"]
ServiceType = Literal["hvac_repair", "hvac_tune_up", "plumbing"]
ConversationStatus = Literal["active", "handed_off", "safety_stop", "ended"]
Banner = Literal["none", "handoff", "safety_stop", "error"]
Action = Literal[
    "ask_solved", "choose_callback_window", "request_callback", "new_conversation"
]
CallbackWindow = Literal["morning", "afternoon", "evening"]


class Choice(Model):
    label: str
    text: str


class Booking(Model):
    appointment_id: int
    slot_id: int
    date: str
    window: str
    technician_name: str
    service_type: ServiceType
    zone: Zone
    diagnostic_fee_cents: int | None
    diagnostic_fee_waived: bool


class Window(Model):
    slot_id: int
    date: str
    window: str
    service_type: str
    zone: Zone
    technician_name: str
    member_only: bool


class CustomerRef(Model):
    customer_id: str
    name: str
    city: str
    zone: Zone | None
    membership_tier: Literal["none", "standard", "plus"]
    membership_renewal_date: str | None
    system_brand: str | None
    system_install_date: str | None


class AppointmentView(Model):
    appointment_id: int
    date: str
    window: str
    technician_name: str
    service_type: str
    zone: Zone
    issue: str
    late_cancel_fee_applies: bool


class LineItem(Model):
    desc: str
    cents: int


class Invoice(Model):
    invoice_id: str
    issued_date: str
    due_date: str
    amount_cents: int
    balance_cents: int
    line_items: list[LineItem]


class Passage(Model):
    passage_id: str
    source_file: str
    section: str
    kind: Literal["text", "table_rows", "price_row", "image_text", "pdf_text"]
    text: str
    score: float


class Fee(Model):
    code: str
    cents: int
    source_file: str


class Verdict(Model):
    verdict: Literal["safe", "burning_followup", "emergency"]
    reason: str


class TurnInfo(Model):
    seq: int
    latency_ms: int


class Reply(Model):
    conversation_id: str
    status: ConversationStatus
    text: str
    banner: Banner
    choices: list[Choice]
    booking: Booking | None
    waitlisted: bool
    actions: list[Action]
    turn: TurnInfo


class HandoffCaller(Model):
    customer_id: str | None
    name: str | None
    phone: str | None
    city: str | None
    zone: Zone | None
    stated_by_caller: bool


class HandoffView(Model):
    id: int
    conversation_public_id: str
    kind: str
    reason: str
    by_error: bool
    caller: HandoffCaller
    intent: str
    told_caller: str
    summary: str
    summary_source: str
    preferred_window: CallbackWindow | None
    status: Literal["open", "followed_up"]
    created_at: str
    followed_up_at: str | None


class WaitlistCaller(Model):
    customer_id: str
    name: str
    phone: str
    city: str


class HeldWindow(Model):
    date: str
    window: str


class WaitlistView(Model):
    id: int
    conversation_public_id: str
    caller: WaitlistCaller
    service_type: str
    zone: Zone
    held: HeldWindow
    created_at: str
    waiting_seconds: int


class ConversationSummary(Model):
    public_id: str
    started_at: str
    ended_at: str | None
    intent: str | None
    outcome: str | None
    outcome_reason: str | None
    turn_count: int
    cost_usd: float
    solved: str | None
    flagged: bool
    has_handoff: bool
    customer_name: str | None


class ToolCall(Model):
    name: str
    ok: bool
    ms: int


class RetrievedRef(Model):
    source_file: str
    score: float


class TurnView(Model):
    seq: int
    kind: str
    caller_text: str
    reply_text: str
    tools_called: list[ToolCall]
    retrieved: list[RetrievedRef]
    safety_verdict: str | None
    latency_ms: int
    error: str | None
    fallback_used: bool
    cost_usd: float
    trace_id: str | None


class FlagView(Model):
    id: int
    note: str
    created_at: str


class EvalCandidateRef(Model):
    scenario_id: str


class ConversationDetail(Model):
    summary: ConversationSummary
    turns: list[TurnView]
    handoff: HandoffView | None
    flags: list[FlagView]
    eval_candidate: EvalCandidateRef | None


class ErrorBody(Model):
    error: str
    message: str


# Overview


class OverviewStatus(Model):
    public_url: str
    last_conversation_at: str | None
    errors_shown_24h: int
    handoffs_waiting: int


class SeriesPoint(Model):
    date: str
    settled_pct: float | None


class OverviewSuccess(Model):
    settled_pct: float | None
    settled_count: int
    total_count: int
    target_band_pct: list[int]
    series: list[SeriesPoint]


class OverviewSupporting(Model):
    booking_completion_pct: float | None
    handoffs_on_handled_topics_pct: float | None
    top_handoff_reason: str | None
    flagged_wrong_pct: float | None


class DayCount(Model):
    date: str
    count: int


class Outcomes(Model):
    contained: int
    handoff: int
    safety_stop: int
    failed: int
    active: int


class OverviewVolume(Model):
    conversations_by_day: list[DayCount]
    outcomes: Outcomes


class RecentConversation(Model):
    public_id: str
    started_at: str
    intent: str | None
    zone: Zone | None
    outcome: str | None
    latency_ms: int | None


class Guarantee(Model):
    key: str
    name: str
    now: float | None
    limit: float
    status: Literal["ok", "breach", "no_data"]


class LatencyPoint(Model):
    hour: str
    p95_first_reply_ms: int | None


class OverviewSpend(Model):
    total_usd: float | None
    alert_usd: float
    alert: bool


class Overview(Model):
    as_of: str
    status: OverviewStatus
    success: OverviewSuccess
    supporting: OverviewSupporting
    volume: OverviewVolume
    recent: list[RecentConversation]
    guarantees: list[Guarantee]
    latency_series_24h: list[LatencyPoint]
    spend: OverviewSpend


# Requests and route responses


class SendMessageRequest(Model):
    text: str
    simulate_outage: bool | None = None


class SolvedRequest(Model):
    answer: str


class CallbackWindowRequest(Model):
    window: CallbackWindow


class FollowedUpRequest(Model):
    followed_up: bool = True


class FlagRequest(Model):
    note: str


class StartConversationResponse(Model):
    conversation_id: str
    status: Literal["active"]
    greeting: str
    demo_faults: bool


class SolvedResponse(Model):
    saved: bool
    status: Literal["ended", "active"]
    text: str
    actions: list[Action]


class CallbackWindowResponse(Model):
    handoff: HandoffView
    text: str


class HandoffList(Model):
    handoffs: list[HandoffView]


class HandoffResponse(Model):
    handoff: HandoffView


class WaitlistList(Model):
    entries: list[WaitlistView]


class ConversationList(Model):
    conversations: list[ConversationSummary]


class FlagInfo(Model):
    id: int
    created_at: str


class FlagCreated(Model):
    flag: FlagInfo


class CandidateCreated(Model):
    candidate: EvalCandidateRef


class HealthComponents(Model):
    scheduling_db: Literal["ok", "error"]
    app_db: Literal["ok", "error"]
    index: Literal["loaded", "missing"]


class Health(Model):
    status: Literal["ok", "degraded"]
    components: HealthComponents


class EvalCandidateItem(Model):
    scenario_id: str
    scenario: dict[str, Any]


class EvalCandidateList(Model):
    candidates: list[EvalCandidateItem]


class RebuildIndexResult(Model):
    index_version: str
    passages: int
    sources: int


class SlotCounts(Model):
    open: int
    booked: int
    reserved_members: int
    blocked: int


class ResetSchedulingResult(Model):
    restored: bool
    snapshot_id: str
    slot_counts: SlotCounts


# Module interface results


class RedactResult(Model):
    text: str
    removed: bool


class IndexStatus(Model):
    loaded: bool
    version: str | None
    passages: int


class OpenWindows(Model):
    windows: list[Window]
    matched_request: bool
    reason: str | None


class MoveResult(Model):
    booking: Booking
    late_fee_applies: bool


class CancelResult(Model):
    appointment_id: int
    freed_slot_id: int
    late_fee_applies: bool
    hours_before: float


class Billing(Model):
    balance_cents: int
    invoices: list[Invoice]


class PaymentLink(Model):
    url: str
    valid_for_hours: int


class ResetResult(Model):
    snapshot_id: str
    slot_counts: SlotCounts


class HandoffRecord(Model):
    conversation_id: str
    kind: str
    reason: str
    by_error: bool
    customer_id: str | None = None
    stated_name: str | None = None
    stated_phone: str | None = None
    intent: str
    told_caller: str
    summary_source: str = "agent"


class WaitlistRequest(Model):
    conversation_id: str
    customer_id: str
    service_type: str
    zone: Zone
    held_date: str
    held_window: str


class JoinWaitlistResult(Model):
    entry: WaitlistView
    created: bool
