import pytest
from fastapi.testclient import TestClient

from app.knowledge.embeddings import FakeEmbedder
from app.main import create_app
from app.settings import Settings

ADMIN = {"Authorization": "Bearer test-admin-token"}


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture
def app_and_client(kb_settings: Settings, embedder: FakeEmbedder):
    app = create_app(kb_settings, embedder=embedder)
    return app, TestClient(app)


def test_route_needs_the_token(app_and_client, embedder: FakeEmbedder):
    app, client = app_and_client
    built = client.post("/admin/rebuild-index", headers=ADMIN)
    assert built.status_code == 200
    body = built.json()
    assert set(body) == {"indexVersion", "passages", "sources"}
    calls = embedder.calls
    for headers in ({}, {"Authorization": "Bearer wrong"}):
        response = client.post("/admin/rebuild-index", headers=headers)
        assert response.status_code == 401
        assert response.json()["error"] == "unauthorized"
    assert embedder.calls == calls
    assert app.state.ctx.index.current().version == body["indexVersion"]


def test_route_reports_manifest_invalid_as_422(app_and_client, kb_settings: Settings):
    _, client = app_and_client
    (kb_settings.KB_DIR / "faq" / "new_note.md").write_text("# New\nText")
    response = client.post("/admin/rebuild-index", headers=ADMIN)
    assert response.status_code == 422
    assert response.json()["error"] == "manifest_invalid"
    assert "faq/new_note.md" in response.json()["message"]
