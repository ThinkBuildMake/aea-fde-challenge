"""S37 gate: failures are counted apart from deliberate handoffs on the Overview (OB-3),
through the real Conversation, Follow-ups and Monitoring modules."""

from typing import Any

from fastapi.testclient import TestClient

from app.llm import FakeModelProvider, ModelResult
from app.monitoring.service import get_overview
from app.settings import Settings
from tests.gate.test_handoff_seams import real_app, send
from tests.test_turn import assistant, result, tool_call


class Scripted(FakeModelProvider):
    """Replies in order; an exception in the script is raised as a provider failure."""

    def __init__(self, script: list[ModelResult | Exception]) -> None:
        super().__init__()
        self.script = list(script)

    def complete(self, messages, *, tools=None, timeout_s):
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def report(intent: str, resolved: bool, *more: dict[str, Any]) -> ModelResult:
    return result(
        assistant(
            calls=[
                tool_call("r", "report_status", intent=intent, resolved=resolved),
                *more,
            ]
        )
    )


def figures(client: TestClient) -> tuple[int, float | None, str | None]:
    overview = get_overview(client.app.state.ctx)  # type: ignore[attr-defined]
    return (
        overview.status.errors_shown_24h,
        overview.supporting.handoffs_on_handled_topics_pct,
        overview.supporting.top_handoff_reason,
    )


def conversation(client: TestClient, text: str, **extra: Any) -> str:
    cid = client.post("/conversations").json()["conversationId"]
    send(client, cid, text, **extra)
    return cid


def test_outage_call_back_counts_as_an_error_not_a_handled_topic_handoff(
    kb_settings: Settings,
):
    settings = kb_settings.model_copy(update={"DEMO_FAULT_INJECTION": True})
    client = real_app(
        settings,
        Scripted([report("book_visit", True), result(assistant("Happy to help."))]),
    )
    conversation(client, "I need a repair visit")
    before = figures(client)
    cid = conversation(client, "Can I move my visit?", simulateOutage=True)
    picked = client.post(
        f"/conversations/{cid}/callback-window", json={"window": "morning"}
    )
    after = figures(client)
    print(
        f"\nbefore: errors={before[0]} handled-topic handoffs={before[1]}%"
        f"\nafter outage + morning call back ({picked.status_code}): "
        f"errors={after[0]} handled-topic handoffs={after[1]}%"
    )
    assert picked.status_code == 200
    assert after[0] == before[0] + 1
    assert before[1] is not None and after[1] == before[1]


def test_failure_handoffs_stay_out_of_handled_topic_handoffs(kb_settings: Settings):
    escalate = tool_call("e", "escalate", reason="out_of_scope", intent="Wants solar")
    client = real_app(
        kb_settings,
        Scripted(
            [
                # (a) a deliberate handoff on a booking conversation
                report("book_visit", False, escalate),
                result(assistant("A person will call you back.")),
                # (b) a booking conversation that hits a provider failure
                report("book_visit", False),
                RuntimeError("provider down"),
                # (c) a booking conversation the agent handles
                report("book_visit", True),
                result(assistant("Which day suits you?")),
            ]
        ),
    )
    deliberate = conversation(client, "I need a visit and solar panels")
    failed = conversation(client, "I need a visit")
    conversation(client, "I need a visit too")
    client.post(
        f"/conversations/{deliberate}/callback-window", json={"window": "evening"}
    )
    picked = client.post(
        f"/conversations/{failed}/callback-window", json={"window": "morning"}
    )
    errors, pct, top = figures(client)
    print(
        f"\nfailure call back: {picked.status_code} {picked.json()['handoff']['reason']}"
        f"\nerrors={errors} handled-topic handoffs={pct}% top reason={top}"
    )
    assert picked.json()["handoff"]["byError"] is True
    assert errors == 1
    assert pct == 33.3 and top == "out_of_scope"
