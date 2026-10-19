"""S29 gate: a policy question through the real Safety, Knowledge and Conversation modules.

Only the network edges are scripted: the safety classifier's reply, the embedder
(FakeEmbedder over a copy of the knowledge base) and the agent model (a recording).
"""

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.conversation import guards
from app.knowledge.embeddings import FakeEmbedder
from app.knowledge.service import rebuild_index
from app.llm import FakeModelProvider, ModelResult
from app.main import create_app
from app.safety.service import OpenRouterSafetyClassifier
from app.settings import Settings
from tests.gate.harness import FakeClock, evaluate_pf1, play_case

RECORDING = Path(__file__).parent / "recorded" / "diagnostic_fee.json"
QUESTION = "Is the diagnostic fee $79?"
HIDDEN = (
    "archive/",
    "faq/faq_old_copy.md",
    "internal/",
    "policies/escalation_and_safety.md",
    "services/technician_arrival_and_etas.md",
)


def recorded(final: str | None = None) -> list[ModelResult]:
    """The recorded model turn; `final` replaces the answer's text."""
    results = []
    for entry in json.loads(RECORDING.read_text())["messages"]:
        message = dict(entry["message"])
        if final is not None and message["content"]:
            message["content"] = final
        results.append(
            ModelResult(
                message,
                prompt_tokens=entry["prompt_tokens"],
                completion_tokens=entry["completion_tokens"],
                cost_usd=entry["cost"],
            )
        )
    return results


def real_app(settings: Settings, model: FakeModelProvider, clock: FakeClock):
    embedder = FakeEmbedder()
    app = create_app(settings, model=model, clock=clock, embedder=embedder)
    rebuild_index(app.state.ctx)
    return TestClient(app), embedder


def rows(settings: Settings, sql: str, *args: Any) -> list[sqlite3.Row]:
    conn = sqlite3.connect(settings.APP_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def ask(client: TestClient, text: str) -> tuple[str, dict[str, Any]]:
    cid = client.post("/conversations").json()["conversationId"]
    response = client.post(f"/conversations/{cid}/messages", json={"text": text})
    assert response.status_code == 200
    return cid, response.json()


def test_retired_fee_is_corrected_through_the_real_seams(kb_settings: Settings):
    model = FakeModelProvider(results=recorded())
    client, _ = real_app(kb_settings, model, FakeClock())

    cid, reply = ask(client, QUESTION)

    print("reply:", reply["text"], "| actions:", reply["actions"])
    assert "$89" in reply["text"] and "$79" not in reply["text"]
    assert "ask_solved" in reply["actions"]
    (turn,) = rows(kb_settings, "SELECT * FROM turns")
    retrieved = {r["sourceFile"] for r in json.loads(turn["retrieved"])}
    print("turn: safety_verdict", turn["safety_verdict"], "error", turn["error"])
    print("retrieved:", sorted(retrieved))
    assert turn["safety_verdict"] == "safe" and turn["error"] is None
    assert "faq/customer_faq.md" in retrieved

    solved = client.post(f"/conversations/{cid}/solved", json={"answer": "yes"})

    print("solved:", solved.status_code, solved.json())
    assert solved.status_code == 200
    assert solved.json()["saved"] is True and solved.json()["status"] == "ended"
    (conv,) = rows(kb_settings, "SELECT solved, outcome FROM conversations")
    print("conversation: solved", conv["solved"], "outcome", conv["outcome"])
    assert (conv["solved"], conv["outcome"]) == ("yes", "contained")


def test_embeddings_failing_offers_a_person(kb_settings: Settings):
    model = FakeModelProvider(results=recorded())
    client, embedder = real_app(kb_settings, model, FakeClock())
    embedder.fail = True

    _, reply = ask(client, QUESTION)

    print("reply:", reply["text"], "| actions:", reply["actions"])
    assert reply["text"] == guards.NOT_SURE_TEXT
    assert "pass you to a person" in reply["text"]
    assert reply["actions"] == ["request_callback"]
    assert "$" not in reply["text"]
    (turn,) = rows(kb_settings, "SELECT error FROM turns")
    print("turn error:", turn["error"])
    assert turn["error"] == "embedding_unavailable"
    tool_messages = [m for m in model.received[1] if m["role"] == "tool"]
    assert any(
        guards.SEARCH_UNAVAILABLE_INSTRUCTION
        in json.loads(m["content"]).get("instruction", "")
        for m in tool_messages
    )


def test_index_holds_only_current_public_files(kb_settings: Settings):
    model = FakeModelProvider(results=recorded())
    client, _ = real_app(kb_settings, model, FakeClock())
    manifest = json.loads((kb_settings.KB_DIR.parent / "kb_manifest.json").read_text())
    current = {
        name for name, e in manifest["files"].items() if e["status"] == "current"
    }

    ask(client, QUESTION)

    loaded = client.app.state.ctx.index.current()  # type: ignore[attr-defined]
    indexed = {p.source_file for p in loaded.passages}
    print("indexed sources:", sorted(indexed))
    assert indexed <= current
    assert not [s for s in indexed if s.startswith(HIDDEN)]
    (turn,) = rows(kb_settings, "SELECT model_messages FROM turns")
    tool_text = " ".join(
        m["content"] for m in json.loads(turn["model_messages"]) if m["role"] == "tool"
    )
    assert "$89" in tool_text and "$79" not in tool_text


def test_a_reply_stating_the_retired_fee_is_withheld(kb_settings: Settings):
    model = FakeModelProvider(results=recorded("Yes, the diagnostic fee is $79."))
    client, _ = real_app(kb_settings, model, FakeClock())

    _, reply = ask(client, QUESTION)

    print("reply:", reply["text"])
    assert reply["text"] == guards.NOT_SURE_TEXT
    assert "$" not in reply["text"]
    (turn,) = rows(kb_settings, "SELECT error, reply_text FROM turns")
    assert turn["error"] == "unsupported_figure"
    assert "$79" not in turn["reply_text"]


@pytest.mark.parametrize(("delay_s", "passes"), [(0.0, True), (7.0, False)])
def test_policy_answer_first_reply_within_pf1(
    kb_settings: Settings, delay_s: float, passes: bool
):
    clock = FakeClock()
    model = FakeModelProvider(results=recorded(), delay_s=delay_s, sleep=clock.advance)
    client, _ = real_app(kb_settings, model, clock)

    verdict = evaluate_pf1(
        [play_case(client, {"id": "GATE-S29-FEE", "opening": QUESTION}, clock)]
    )

    print(verdict.message)
    assert verdict.passed is passes


CARDS = [
    "4111111111111111",
    "4111 1111 1111 1111",
    "4111-1111-1111-1111",
    "3782 822463 10005",
    "4222222222222",
]


def test_five_card_messages_are_kept_nowhere(
    kb_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
):
    screened: list[Any] = []

    def classify(self, messages, timeout_s):
        screened.append(messages)
        return '{"verdict": "safe", "reason": "no_hazard"}'

    monkeypatch.setattr(OpenRouterSafetyClassifier, "classify", classify)
    model = FakeModelProvider(
        results=[
            ModelResult({"role": "assistant", "content": "Thanks, please go on."})
            for _ in CARDS
        ]
    )
    client, _ = real_app(kb_settings, model, FakeClock())
    cid = client.post("/conversations").json()["conversationId"]

    for card in CARDS:
        response = client.post(
            f"/conversations/{cid}/messages", json={"text": f"My card is {card} ok"}
        )
        assert response.status_code == 200

    stored = rows(
        kb_settings, "SELECT caller_text, reply_text, model_messages FROM turns"
    )
    places = {
        "turns": json.dumps([dict(r) for r in stored]),
        "classifier": json.dumps(screened),
        "model": json.dumps(model.received),
        "stdout": "".join(capfd.readouterr()),
    }
    assert len(stored) == 5 and len(screened) == 5
    for place, text in places.items():
        digits = re.sub(r"[ \-]", "", text)
        for card in CARDS:
            assert re.sub(r"\D", "", card) not in digits, (place, card)
