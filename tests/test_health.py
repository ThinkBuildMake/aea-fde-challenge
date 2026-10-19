import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.llm import FakeModelProvider
from app.main import create_app
from app.settings import Settings
from app.types import IndexStatus


@pytest.fixture
def client(started: Settings) -> TestClient:
    return TestClient(create_app(started, model=FakeModelProvider()))


def stub_parts(monkeypatch: pytest.MonkeyPatch, *, loaded: bool, scheduling: str):
    monkeypatch.setattr(
        "app.monitoring.service.index_status",
        lambda ctx: IndexStatus(
            loaded=loaded, version="v1" if loaded else None, passages=1 if loaded else 0
        ),
    )
    monkeypatch.setattr(
        "app.monitoring.service.scheduling_status", lambda ctx: scheduling
    )


def test_all_healthy_reports_ok(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    stub_parts(monkeypatch, loaded=True, scheduling="ok")
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "components": {"schedulingDb": "ok", "appDb": "ok", "index": "loaded"},
    }


def test_head_returns_200_without_body(client: TestClient):
    response = client.head("/health")
    assert response.status_code == 200
    assert response.content == b""


def test_missing_index_is_named(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    stub_parts(monkeypatch, loaded=False, scheduling="ok")
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "degraded",
        "components": {"schedulingDb": "ok", "appDb": "ok", "index": "missing"},
    }


@pytest.mark.parametrize("failing", ["schedulingDb", "appDb"])
def test_failing_part_is_named_and_still_200(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, failing: str
):
    stub_parts(
        monkeypatch,
        loaded=True,
        scheduling="error" if failing == "schedulingDb" else "ok",
    )
    if failing == "appDb":

        def broken() -> sqlite3.Connection:
            raise sqlite3.OperationalError("unreadable")

        monkeypatch.setattr(client.app.state.ctx, "open_app_db", broken)  # type: ignore[attr-defined]
    response = client.get("/health")
    assert response.status_code == 200
    expected = {"schedulingDb": "ok", "appDb": "ok", "index": "loaded"}
    expected[failing] = "error"
    assert response.json() == {"status": "degraded", "components": expected}


def test_missing_app_db_is_error_and_not_created(
    client: TestClient, started: Settings, monkeypatch: pytest.MonkeyPatch
):
    stub_parts(monkeypatch, loaded=True, scheduling="ok")
    db = started.APP_DB_PATH
    for path in (db, db.with_name(db.name + "-wal"), db.with_name(db.name + "-shm")):
        path.unlink(missing_ok=True)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "degraded",
        "components": {"schedulingDb": "ok", "appDb": "error", "index": "loaded"},
    }
    assert not db.exists()
