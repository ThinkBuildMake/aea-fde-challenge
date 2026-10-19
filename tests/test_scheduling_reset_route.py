import hashlib
import sqlite3
import time
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings

AUTH = {"Authorization": "Bearer test-admin-token"}
URL = "/admin/reset-scheduling"


@pytest.fixture
def client(started: Settings) -> TestClient:
    return TestClient(create_app(started))


def test_reset_waits_for_a_booking_and_answers_busy(started, client):
    path = started.SCHEDULING_DB_PATH
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    holder = sqlite3.connect(path, isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    holder.execute("UPDATE appointment_slots SET status='booked' WHERE slot_id=56")
    try:
        start = time.monotonic()
        response = client.post(URL, headers=AUTH)
        waited = time.monotonic() - start
    finally:
        holder.execute("ROLLBACK")
        holder.close()
    print("status", response.status_code, response.json(), f"waited {waited:.1f}s")
    assert response.status_code == 409
    assert response.json()["error"] == "busy"
    assert waited >= 4.5
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert not (path.parent / "backups").exists()


def test_route_restores_with_the_token(started, client):
    with closing(sqlite3.connect(started.SCHEDULING_DB_PATH)) as db:
        db.execute("UPDATE appointment_slots SET status='booked' WHERE slot_id=56")
        db.commit()
    for headers in ({}, {"Authorization": "Bearer wrong"}):
        assert client.post(URL, headers=headers).status_code == 401
    assert not (started.SCHEDULING_DB_PATH.parent / "backups").exists()
    response = client.post(URL, headers={**AUTH, "Accept": "application/json"})
    body = response.json()
    print(response.status_code, body)
    assert response.status_code == 200
    assert body["restored"] is True and body["snapshotId"]
    assert body["slotCounts"] == {
        "open": 323,
        "booked": 159,
        "reservedMembers": 42,
        "blocked": 4,
    }
