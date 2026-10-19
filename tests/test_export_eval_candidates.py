import json
import re
import sqlite3
from pathlib import Path

import httpx2
import pytest
from fastapi.testclient import TestClient

from app.evals import records
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
    # The random hex ids can hold a long run of digits by chance; drop them first.
    text = (out / f"CAND-{public[:8]}.json").read_text().replace(public, "")
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
        # The random hex ids can hold a long run of digits by chance; drop them first.
        text = text.replace(public, "").replace(_secret, "")
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


def mock_client(body: bytes) -> httpx2.Client:
    def answer(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=body)

    return httpx2.Client(transport=httpx2.MockTransport(answer))


@pytest.mark.parametrize(
    "body",
    [
        json.dumps(
            {
                "candidates": [
                    {"scenarioId": "CAND-aaaaaaaa", "scenario": {}},
                    {"bad": 1},
                ]
            }
        ).encode(),
        b"<html>not json</html>",
        json.dumps({"candidates": {"scenarioId": "CAND-aaaaaaaa"}}).encode(),
        json.dumps([1, 2]).encode(),
    ],
    ids=["one_bad_item", "not_json", "not_a_list", "no_candidates_key"],
)
def test_malformed_answer_writes_nothing(body, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token")
    out = tmp_path / "eval" / "candidates"

    code = export.main(
        ["http://testserver", "--out", str(out)], client=mock_client(body)
    )

    err = capsys.readouterr().err
    print("exit", code, "| stderr", err.strip(), "| out exists", out.exists())
    assert code == 1
    assert json.loads(err)["error"] == "export_failed"
    assert not out.exists()


def test_filled_draft_loads_as_a_scenario(client, started, tmp_path):
    _, public = draft(client, started, ["hello there", "book me in"])
    out = tmp_path / "eval" / "candidates"
    assert run(client, out) == 0
    exported = json.loads((out / f"CAND-{public[:8]}.json").read_text())
    filled = {
        **exported,
        "driver": "demo",
        "kind": "edge",
        "expected": {**exported["expected"], "outcome": "contained"},
    }
    folder = tmp_path / "scenarios"
    folder.mkdir()
    (folder / f"CAND-{public[:8]}.json").write_text(json.dumps(filled))

    (scenario,) = records.load_scenarios(folder)

    print(scenario.id, scenario.based_on, scenario.opening, scenario.expected.outcome)
    assert scenario.id == f"CAND-{public[:8]}"
    assert scenario.based_on == public
    assert scenario.opening == "hello there"
    assert scenario.customer_id == exported["customerId"]
    assert scenario.expected.outcome == "contained"
