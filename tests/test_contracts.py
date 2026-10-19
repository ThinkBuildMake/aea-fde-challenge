import sqlite3
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app import types as t
from app.knowledge.embeddings import FakeEmbedder
from app.llm import FakeModelProvider
from app.main import create_app
from app.settings import Settings

ADMIN = {"Authorization": "Bearer test-admin-token"}


@pytest.fixture
def client(kb_settings: Settings) -> TestClient:
    return TestClient(
        create_app(kb_settings, model=FakeModelProvider(), embedder=FakeEmbedder())
    )


@pytest.fixture
def ids(client: TestClient, kb_settings: Settings) -> dict[str, str]:
    conversation_id = client.post("/conversations").json()["conversationId"]
    conn = sqlite3.connect(kb_settings.APP_DB_PATH)
    public_id = conn.execute(
        "SELECT public_id FROM conversations WHERE id = ?", (conversation_id,)
    ).fetchone()[0]
    conn.close()
    return {"id": conversation_id, "public": public_id}


# (method, path template, body, headers, status, response model)
Case = tuple[str, str, dict[str, Any] | None, dict[str, str], int, type[BaseModel]]
CASES: list[Case] = [
    ("POST", "/conversations", None, {}, 201, t.StartConversationResponse),
    ("POST", "/conversations/{id}/messages", {"text": "hi"}, {}, 200, t.Reply),
    (
        "POST",
        "/conversations/{id}/solved",
        {"answer": "yes"},
        {},
        200,
        t.SolvedResponse,
    ),
    (
        "POST",
        "/conversations/{id}/callback-window",
        {"window": "morning"},
        {},
        200,
        t.CallbackWindowResponse,
    ),
    ("GET", "/handoffs", None, {}, 200, t.HandoffList),
    ("POST", "/handoffs/1/followed-up", None, {}, 200, t.HandoffResponse),
    ("GET", "/waitlist", None, {}, 200, t.WaitlistList),
    ("GET", "/overview", None, {}, 200, t.Overview),
    ("GET", "/conversations", None, {}, 200, t.ConversationList),
    ("GET", "/conversations/{public}", None, {}, 200, t.ConversationDetail),
    (
        "POST",
        "/conversations/{public}/flag",
        {"note": "wrong fee"},
        {},
        201,
        t.FlagCreated,
    ),
    (
        "POST",
        "/conversations/{public}/eval-candidate",
        None,
        {},
        201,
        t.CandidateCreated,
    ),
    ("GET", "/health", None, {}, 200, t.Health),
    ("GET", "/admin/eval-candidates", None, ADMIN, 200, t.EvalCandidateList),
    ("POST", "/admin/rebuild-index", None, ADMIN, 200, t.RebuildIndexResult),
    ("POST", "/admin/reset-scheduling", None, ADMIN, 200, t.ResetSchedulingResult),
]


def call(client: TestClient, case: Case, ids: dict[str, str], extra: dict[str, str]):
    method, path, body, headers, _, _ = case
    return client.request(
        method,
        path.format(id=ids["id"], public=ids["public"]),
        json=body,
        headers={**headers, **extra},
    )


@pytest.mark.parametrize("case", CASES, ids=[f"{c[0]} {c[1]}" for c in CASES])
def test_route_answers_its_contract(
    client: TestClient, ids: dict[str, str], case: Case
):
    response = call(client, case, ids, {})
    assert response.status_code == case[4]
    assert response.headers["content-type"].startswith("application/json")
    case[5].model_validate(response.json(), by_alias=True, by_name=False)


@pytest.mark.parametrize("case", CASES, ids=[f"{c[0]} {c[1]}" for c in CASES])
def test_route_answers_an_html_fragment_for_htmx(
    client: TestClient, ids: dict[str, str], case: Case
):
    response = call(client, case, ids, {"HX-Request": "true"})
    assert response.status_code == case[4]
    assert response.headers["content-type"].startswith("text/html")
    assert "<html" not in response.text.lower()
    for name, field in case[5].model_fields.items():
        key = field.alias or name
        assert f'data-field="{key}"' in response.text


def test_admin_routes_refuse_without_the_token(client: TestClient):
    for method, path in [
        ("GET", "/admin/eval-candidates"),
        ("POST", "/admin/rebuild-index"),
        ("POST", "/admin/reset-scheduling"),
    ]:
        response = client.request(method, path)
        assert response.status_code == 401
        assert response.json()["error"] == "unauthorized"


def test_camel_case_keys_in_the_start_response(client: TestClient):
    body = client.post("/conversations").json()
    assert set(body) == {"conversationId", "status", "greeting", "demoFaults"}
    assert body["status"] == "active"


def test_eval_candidate_scenario_id_does_not_leak_the_secret_conversation_id(
    client: TestClient, ids: dict[str, str]
):
    response = client.post(f"/conversations/{ids['public']}/eval-candidate")
    scenario_id = response.json()["candidate"]["scenarioId"]
    assert ids["id"][:8] not in scenario_id
    assert scenario_id == "CAND-" + ids["public"][:8]
