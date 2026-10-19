import pytest
from fastapi.testclient import TestClient

from app.llm import FakeModelProvider
from app.main import create_app
from app.settings import Settings

DIRECTIVES = [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    "frame-ancestors 'none'",
]


@pytest.fixture
def client(started: Settings, overview_stub) -> TestClient:
    return TestClient(create_app(started, model=FakeModelProvider()))


@pytest.fixture
def overview_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.monitoring import routes
    from tests.test_overview_view import make_overview

    monkeypatch.setattr(routes, "get_overview", lambda ctx, *a, **k: make_overview())


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/"),
        ("GET", "/business"),
        ("GET", "/overview"),
        ("GET", "/health"),
        ("GET", "/static/chat.js"),
        ("GET", "/no-such-page"),
        ("POST", "/conversations"),
    ],
)
def test_pages_carry_security_headers(client: TestClient, method: str, path: str):
    response = client.request(method, path)

    policy = response.headers["content-security-policy"]
    print(method, path, response.status_code, "CSP:", policy)
    assert all(d in policy for d in DIRECTIVES)
    assert "unsafe-inline" not in policy and "unsafe-eval" not in policy
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "same-origin"


def test_no_cross_origin_access(client: TestClient):
    origin = {"Origin": "https://example.org"}

    post = client.post("/conversations", headers=origin)
    preflight = client.options(
        "/conversations",
        headers={**origin, "Access-Control-Request-Method": "POST"},
    )

    print(
        "POST",
        post.status_code,
        "ACAO:",
        post.headers.get("access-control-allow-origin"),
    )
    print(
        "OPTIONS",
        preflight.status_code,
        "ACAO:",
        preflight.headers.get("access-control-allow-origin"),
    )
    assert post.status_code == 201
    assert "access-control-allow-origin" not in post.headers
    assert "access-control-allow-origin" not in preflight.headers
