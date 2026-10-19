import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.llm import FakeModelProvider
from app.main import create_app
from app.settings import Settings


@pytest.fixture
def client(started: Settings) -> TestClient:
    return TestClient(create_app(started, model=FakeModelProvider()))


def test_unknown_conversation_answers_404_in_the_one_error_format(client: TestClient):
    response = client.post("/conversations/not-a-real-id/messages", json={"text": "hi"})
    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"error", "message"}
    assert body["error"] == "conversation_not_found"
    assert isinstance(body["message"], str) and body["message"]
    assert "Traceback" not in response.text and 'File "' not in response.text


@pytest.mark.parametrize(
    ("method", "path", "body", "status", "code"),
    [
        ("POST", "/conversations/x/messages", {"nope": 1}, 422, "invalid_request"),
        ("GET", "/no-such-route", None, 404, "not_found"),
        ("DELETE", "/health", None, 405, "method_not_allowed"),
        ("GET", "/handoffs?status=bogus", None, 422, "invalid_status"),
    ],
)
def test_other_failures_use_the_same_format(
    client: TestClient,
    method: str,
    path: str,
    body: dict | None,
    status: int,
    code: str,
):
    response = client.request(method, path, json=body)
    assert response.status_code == status
    assert response.json()["error"] == code
    assert set(response.json()) == {"error", "message"}
    assert "Traceback" not in response.text


def test_error_bodies_stay_json_under_htmx(client: TestClient):
    response = client.post(
        "/conversations/not-a-real-id/messages",
        json={"text": "hi"},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


def test_unexpected_exception_is_a_500_without_a_trace(started: Settings):
    app = create_app(started, model=FakeModelProvider())
    router = APIRouter()

    @router.get("/_boom")
    def boom():
        raise RuntimeError("secret internals")

    app.include_router(router)
    response = TestClient(app, raise_server_exceptions=False).get("/_boom")
    assert response.status_code == 500
    assert response.json()["error"] == "internal_error"
    assert "secret internals" not in response.text
    assert "Traceback" not in response.text
