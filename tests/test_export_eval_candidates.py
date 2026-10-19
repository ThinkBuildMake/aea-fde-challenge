import json
import re
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.llm import FakeModelProvider
from app.main import create_app
from app.monitoring import export
from app.safety.service import CARD_RUN
from app.settings import Settings

CARDS = [
    "my card is 4111 1111 1111 1111",
    "or 4111-1111-1111-1111",
    "4111111111111111",
    "amex 3782 822463 10005",
    "1234567890123",
]


@pytest.fixture
def client(started: Settings, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token")
    return TestClient(create_app(started, model=FakeModelProvider()))


def draft(client: TestClient, started: Settings, texts: list[str]) -> tuple[str, str]:
    secret = client.post("/conversations").json()["conversationId"]
    for text in texts:
        assert client.post(f"/conversations/{secret}/messages", json={"text": text})
    conn = sqlite3.connect(started.APP_DB_PATH)
    conn.execute(
        "UPDATE conversations SET outcome = 'contained',"
        " ended_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?",
        (secret,),
    )
    public = conn.execute(
        "SELECT public_id FROM conversations WHERE id = ?", (secret,)
    ).fetchone()[0]
    conn.commit()
    conn.close()
    assert client.post(f"/conversations/{public}/eval-candidate").status_code == 201
    return secret, public


def run(client: TestClient, out: Path) -> int:
    return export.main(["http://testserver", "--out", str(out)], client=client)


def test_export_writes_the_draft(client, started, tmp_path):
    _, public = draft(client, started, ["hello there", "book me in"])
    out = tmp_path / "eval" / "candidates"
    assert run(client, out) == 0
    file = out / f"CAND-{public[:8]}.json"
    scenario = json.loads(file.read_text())
    print(sorted(p.name for p in out.iterdir()), scenario["callerMessages"])
    assert scenario["callerMessages"] == ["hello there", "book me in"]
    assert scenario["observed"]["outcome"] == "contained"
    assert scenario["expected"] == {
        "outcome": None, "facts": [], "forbidden": [], "dbChange": None,
        "handoffReason": None,
    }  # fmt: skip
    first = file.read_bytes()
    assert run(client, out) == 0
    assert file.read_bytes() == first


def test_exported_file_has_no_card_number(client, started, tmp_path):
    _, public = draft(client, started, [CARDS[0]])
    out = tmp_path / "out"
    assert run(client, out) == 0
    text = (out / f"CAND-{public[:8]}.json").read_text()
    assert not re.search(r"\d{13,19}", text) and not CARD_RUN.search(text)


def test_five_card_messages_never_reach_a_draft(client, started, tmp_path):
    _secret, public = draft(client, started, CARDS)
    out = tmp_path / "out"
    assert run(client, out) == 0
    texts = [
        client.get(f"/conversations/{public}").text,
        client.get("/admin/eval-candidates", headers={"Authorization": "Bearer test-admin-token"}).text,
        (out / f"CAND-{public[:8]}.json").read_text(),
    ]  # fmt: skip
    for text in texts:
        assert not re.search(r"\d{13,19}", text) and not CARD_RUN.search(text)


def test_export_without_token_writes_nothing(
    client, started, tmp_path, monkeypatch, capsys
):
    secret, _ = draft(client, started, ["hello"])
    monkeypatch.setenv("ADMIN_TOKEN", "wrong")
    out = tmp_path / "out"
    assert run(client, out) == 1
    assert "unauthorized" in capsys.readouterr().err
    assert not out.exists()
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token")
    run(client, out)
    assert all(secret not in f.read_text() for f in out.iterdir())
