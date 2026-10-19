"""The overview and health seams through the real Monitoring, Conversation, Knowledge and Scheduling modules."""

import re
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.knowledge.embeddings import FakeEmbedder
from app.llm import FakeModelProvider
from app.main import create_app
from app.monitoring.spend import KeyUsageReader
from app.settings import Settings

ADMIN = {"Authorization": "Bearer test-admin-token"}
JSON = {"Accept": "application/json"}

# S29's seven questions; the caller taps "Yes" on the first.
S29_QUESTIONS = [
    "Is the diagnostic fee $79?",
    "Are you open the day after Thanksgiving?",
    "What does an after-hours emergency visit cost?",
    "How much does it cost to replace a run capacitor?",
    "What fees are agents allowed to waive for me?",
    "Is my AC compressor covered by warranty?",
    "Are you open on Sundays?",
]


class Fixed:
    def __init__(self, usd: float) -> None:
        self.usd = usd

    def read(self) -> float:
        return self.usd


class Failing:
    def read(self) -> float:
        raise RuntimeError("provider down")


def make_client(settings: Settings, key_usage: KeyUsageReader | None = None):
    return TestClient(
        create_app(
            settings,
            model=FakeModelProvider(),
            embedder=FakeEmbedder(),
            key_usage=key_usage,
        )
    )


@pytest.fixture
def client(kb_settings: Settings) -> TestClient:
    return make_client(kb_settings)


def play(client: TestClient, text: str, solved: str | None = None) -> str:
    """One caller conversation through the public routes; returns the caller's id."""
    cid = client.post("/conversations").json()["conversationId"]
    assert client.post(f"/conversations/{cid}/messages", json={"text": text}).is_success
    if solved:
        answered = client.post(f"/conversations/{cid}/solved", json={"answer": solved})
        assert answered.is_success
    return cid


def age(settings: Settings, cid: str, minutes: int) -> None:
    """Move a conversation's last activity into the past."""
    past = datetime.now(UTC) - timedelta(minutes=minutes)
    stamp = past.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    with closing(sqlite3.connect(settings.APP_DB_PATH)) as db, db:
        db.execute(
            "UPDATE conversations SET last_activity_at = ? WHERE id = ?", (stamp, cid)
        )


def row(settings: Settings, cid: str) -> tuple:
    with closing(sqlite3.connect(settings.APP_DB_PATH)) as db:
        return db.execute(
            "SELECT outcome, outcome_reason, ended_at, public_id FROM conversations "
            "WHERE id = ?",
            (cid,),
        ).fetchone()


def text_of(html: str, pattern: str) -> str:
    match = re.search(pattern, html, re.DOTALL)
    assert match, pattern
    return re.sub(r"\s+", " ", match.group(1)).strip()


def test_settled_reads_one_of_seven(client: TestClient):
    for i, question in enumerate(S29_QUESTIONS):
        play(client, question, solved="yes" if i == 0 else None)

    success = client.get("/overview", headers=JSON).json()["success"]
    html = client.get("/business").text

    line = text_of(html, r'<div class="count-line">(.*?)</div>')
    print("success", success, "| count-line:", line)
    assert (success["settledCount"], success["totalCount"]) == (1, 7)
    assert success["settledPct"] == 14.3
    assert line.startswith("1 of 7 conversations")


def test_idle_conversation_is_counted_as_failed(
    client: TestClient, kb_settings: Settings
):
    cid = play(client, "Is my AC compressor covered by warranty?")
    age(kb_settings, cid, 31)

    outcomes = client.get("/overview", headers=JSON).json()["volume"]["outcomes"]
    html = client.get("/business").text

    failed = text_of(html, r'<li data-outcome="failed">(.*?)</li>')
    outcome, reason, _, _ = row(kb_settings, cid)
    print("outcomes", outcomes, "| row", outcome, reason, "| page:", failed)
    assert outcomes["failed"] == 1 and outcomes["active"] == 0
    assert (outcome, reason) == ("failed", "idle_unresolved")
    assert failed == "Failed 1"


def test_idle_closed_before_numbers_are_read(client: TestClient, kb_settings: Settings):
    cid = play(client, "Are you open on Sundays?")
    age(kb_settings, cid, 31)
    assert row(kb_settings, cid)[0] is None

    outcomes = client.get("/overview", headers=JSON).json()["volume"]["outcomes"]

    outcome, reason, ended_at, _ = row(kb_settings, cid)
    print("one GET /overview:", outcomes, "| row", outcome, reason, ended_at)
    assert outcomes["failed"] == 1 and outcomes["active"] == 0
    assert (outcome, reason) == ("failed", "idle_unresolved")
    assert ended_at is not None


def test_spend_banner_when_threshold_below_total(kb_settings: Settings):
    settings = kb_settings.model_copy(update={"SPEND_ALERT_USD": 10.0})
    client = make_client(settings, Fixed(12.5))

    body = client.get("/overview", headers=JSON).json()
    html = client.get("/business").text

    co1 = next(g for g in body["guarantees"] if g["key"] == "CO-1")
    banner = text_of(
        html, r'<div class="banner[^"]*" data-banner="spend"[^>]*>(.*?)</div>'
    )
    line = text_of(html, r"<p [^>]*data-spend-line>(.*?)</p>")
    print(
        "spend",
        body["spend"],
        "CO-1",
        co1["status"],
        "| banner:",
        banner,
        "| line:",
        line,
    )
    assert body["spend"] == {"totalUsd": 12.5, "alertUsd": 10.0, "alert": True}
    assert co1["status"] == "breach"
    assert banner == "Total model spend has passed the $10 alert."
    assert line == "Total model spend: $12.50 of the $10 alert."


def test_overview_loads_when_key_usage_fails(kb_settings: Settings):
    client = make_client(kb_settings, Failing())
    play(client, "Are you open on Sundays?", solved="yes")

    response = client.get("/overview", headers=JSON)
    page = client.get("/business")

    body = response.json()
    co1 = next(g for g in body["guarantees"] if g["key"] == "CO-1")
    line = text_of(page.text, r"<p [^>]*data-spend-line>(.*?)</p>")
    print(
        response.status_code,
        "spend",
        body["spend"],
        "CO-1",
        co1["status"],
        "| settled",
        body["success"]["settledCount"],
        "of",
        body["success"]["totalCount"],
        "|",
        page.status_code,
        line,
    )
    assert response.status_code == 200 and page.status_code == 200
    assert body["spend"] == {"totalUsd": None, "alertUsd": 100.0, "alert": False}
    assert co1["status"] == "no_data"
    assert (body["success"]["settledCount"], body["success"]["totalCount"]) == (1, 1)
    assert line == "Total model spend: unknown of the $100 alert."
    assert 'data-banner="spend"' not in page.text


def test_health_ok_with_the_real_parts(client: TestClient):
    assert client.post("/admin/rebuild-index", headers=ADMIN).status_code == 200

    response = client.get("/health")

    print(response.status_code, response.json())
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "components": {"schedulingDb": "ok", "appDb": "ok", "index": "loaded"},
    }


DEGRADED = {
    "status": "degraded",
    "components": {"schedulingDb": "ok", "appDb": "ok", "index": "missing"},
}


@pytest.mark.parametrize("how", ["never_built", "file_deleted"])
def test_health_degraded_when_index_file_missing(
    client: TestClient, kb_settings: Settings, how: str
):
    if how == "file_deleted":
        assert client.post("/admin/rebuild-index", headers=ADMIN).status_code == 200
        assert client.get("/health").json()["components"]["index"] == "loaded"
        kb_settings.INDEX_PATH.unlink()
    assert not kb_settings.INDEX_PATH.exists()

    response = client.get("/health")

    print(how, response.status_code, response.json())
    assert response.status_code == 200
    assert response.json() == DEGRADED


def test_recent_names_conversations_by_public_id(
    client: TestClient, kb_settings: Settings
):
    cid = play(client, "Are you open on Sundays?")
    public = row(kb_settings, cid)[3]

    overview = client.get("/overview", headers=JSON)
    html = client.get("/business").text

    print("recent[0].publicId", overview.json()["recent"][0]["publicId"])
    assert overview.json()["recent"][0]["publicId"] == public
    assert cid not in overview.text
    assert cid not in html
