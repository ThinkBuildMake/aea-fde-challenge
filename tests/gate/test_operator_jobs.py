"""S40 gate: the operator jobs through the real Knowledge, Scheduling and Conversation modules.

Only the network edges are scripted: the embedder (FakeEmbedder over a copy of the
knowledge base) and the agent model (FakeModelProvider). CH-1: a listed document
answers after one rebuild with no code change; DP-4 / admin routes need the token.
"""

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.knowledge.embeddings import FakeEmbedder
from app.llm import FakeModelProvider, ModelResult
from app.main import create_app
from app.scheduling.service import book_visit
from app.settings import Settings
from tests.gate.harness import FakeClock

ADMIN = {"Authorization": "Bearer test-admin-token"}
NEW_DOC = "faq/filter_swap_clinic.md"
UNLISTED = "faq/unlisted_note.md"
QUESTION = "Do you have a filter swap clinic? Where and when is it?"
CLINIC = (
    "# Filter swap clinic\n\n**Do you run a filter swap clinic?** Yes. Meridian runs a "
    "free filter swap clinic on the first Saturday of every month, 9 AM to noon, at our "
    "shop at 412 Larkspur Lane, Kyle."
)


def assistant(message: dict[str, Any]) -> ModelResult:
    return ModelResult(
        message, prompt_tokens=1000, completion_tokens=30, cost_usd=0.0003
    )


def scripted_turn() -> list[ModelResult]:
    """One recorded-shape turn: search the knowledge base, report status, answer."""
    calls = [
        ("call_search_1", "search_knowledge", {"query": "filter swap clinic"}),
        (
            "call_status_1",
            "report_status",
            {"intent": "policy_question", "resolved": True},
        ),
    ]
    return [
        assistant(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(args)},
                    }
                    for call_id, name, args in calls
                ],
            }
        ),
        assistant(
            {
                "role": "assistant",
                "content": "Yes. The free filter swap clinic runs on the first "
                "Saturday of every month, 9 AM to noon, at 412 Larkspur Lane, Kyle.",
            }
        ),
    ]


def real_app(settings: Settings, turns: int = 1):
    embedder = FakeEmbedder()
    model = FakeModelProvider(
        results=[r for _ in range(turns) for r in scripted_turn()]
    )
    app = create_app(settings, model=model, clock=FakeClock(), embedder=embedder)
    return app, TestClient(app), embedder


def ask_retrieved(client: TestClient, settings: Settings) -> set[str]:
    """Ask the question in a new conversation; return the sources its turn retrieved."""
    cid = client.post("/conversations").json()["conversationId"]
    response = client.post(f"/conversations/{cid}/messages", json={"text": QUESTION})
    assert response.status_code == 200
    with closing(sqlite3.connect(settings.APP_DB_PATH)) as db:
        (retrieved,) = db.execute(
            "SELECT retrieved FROM turns ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
    return {r["sourceFile"] for r in json.loads(retrieved)}


def add_to_manifest(kb_dir: Path, rel: str) -> None:
    path = kb_dir.parent / "kb_manifest.json"
    manifest = json.loads(path.read_text())
    manifest["files"][rel] = {"status": "current", "reason": "S40 gate document."}
    path.write_text(json.dumps(manifest, indent=2))


def test_a_new_listed_document_answers_after_one_rebuild(kb_settings: Settings):
    _, client, _ = real_app(kb_settings)
    (kb_settings.KB_DIR / NEW_DOC).write_text(CLINIC)
    add_to_manifest(kb_settings.KB_DIR, NEW_DOC)

    built = client.post("/admin/rebuild-index", headers=ADMIN)

    print("rebuild:", built.status_code, built.json())
    assert built.status_code == 200
    assert built.json()["sources"] == 10
    retrieved = ask_retrieved(client, kb_settings)
    print("retrieved:", sorted(retrieved))
    assert NEW_DOC in retrieved


def test_an_unlisted_document_is_refused_and_answers_are_unchanged(
    kb_settings: Settings,
):
    app, client, _ = real_app(kb_settings, turns=2)
    first = client.post("/admin/rebuild-index", headers=ADMIN)
    assert first.status_code == 200
    version = app.state.ctx.index.current().version
    before = ask_retrieved(client, kb_settings)
    (kb_settings.KB_DIR / UNLISTED).write_text(
        "# Note\nThe clinic moved to 99 Oak Street."
    )

    refused = client.post("/admin/rebuild-index", headers=ADMIN)

    print("rebuild:", refused.status_code, refused.json())
    assert refused.status_code == 422
    assert refused.json()["error"] == "manifest_invalid"
    assert UNLISTED in refused.json()["message"]
    after_version = app.state.ctx.index.current().version
    print("index version:", version, "->", after_version)
    assert after_version == version
    after = ask_retrieved(client, kb_settings)
    print("retrieved before:", sorted(before), "after:", sorted(after))
    assert after == before


def slot_counts(settings: Settings) -> dict[str, int]:
    with closing(sqlite3.connect(settings.SCHEDULING_DB_PATH)) as db:
        return dict(
            db.execute(
                "SELECT status, count(*) FROM appointment_slots GROUP BY status"
            ).fetchall()
        )


def slot_56(settings: Settings) -> str:
    with closing(sqlite3.connect(settings.SCHEDULING_DB_PATH)) as db:
        return db.execute(
            "SELECT status FROM appointment_slots WHERE slot_id=56"
        ).fetchone()[0]


def test_admin_routes_need_the_token_with_the_real_modules(kb_settings: Settings):
    app, client, embedder = real_app(kb_settings)
    ctx = app.state.ctx
    assert client.post("/admin/rebuild-index", headers=ADMIN).status_code == 200
    version, calls = ctx.index.current().version, embedder.calls
    with closing(ctx.open_app_db()) as db:
        cid = db.execute(
            "INSERT INTO conversations DEFAULT VALUES RETURNING id"
        ).fetchone()[0]
    book_visit(ctx, "MHC-10001", 56, "AC blowing warm air", cid)
    counts = slot_counts(kb_settings)

    for path in ("/admin/reset-scheduling", "/admin/rebuild-index"):
        for headers in ({}, {"Authorization": "Bearer wrong"}):
            response = client.post(path, headers=headers)
            print(
                path, headers or "no token", "->", response.status_code, response.json()
            )
            assert response.status_code == 401
            assert response.json()["error"] == "unauthorized"

    print("slot counts:", slot_counts(kb_settings), "slot 56:", slot_56(kb_settings))
    assert slot_counts(kb_settings) == counts
    assert slot_56(kb_settings) == "booked"
    assert not (kb_settings.SCHEDULING_DB_PATH.parent / "backups").exists()
    print("index version:", version, "->", ctx.index.current().version)
    print("embedder calls:", calls, "->", embedder.calls)
    assert ctx.index.current().version == version
    assert embedder.calls == calls
