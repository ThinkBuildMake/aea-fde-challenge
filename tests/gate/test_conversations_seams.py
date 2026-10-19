"""S38 gate: the Conversations tab's seams through the real Monitoring and Conversation modules.

list -> idle close -> detail -> flag -> draft -> export, with only the network edges
scripted (the agent model, the embedder and the safety screen's reply).
"""

import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.llm import FakeModelProvider
from app.monitoring import export
from app.safety.service import CARD_RUN
from app.settings import Settings
from tests.gate.harness import FakeClock
from tests.gate.test_overview_seams import age, play, row
from tests.gate.test_policy_answer import QUESTION, real_app, recorded

ADMIN = {"Authorization": "Bearer test-admin-token"}
EMPTY_EXPECTED = {
    "outcome": None,
    "facts": [],
    "forbidden": [],
    "dbChange": None,
    "handoffReason": None,
}
# The CARDS list from tests/test_export_eval_candidates.py.
CARDS = [
    "my card is 4111 1111 1111 1111",
    "or 4111-1111-1111-1111",
    "4111111111111111",
    "amex 3782 822463 10005",
    "1234567890123",
]


@pytest.fixture
def client(kb_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token")
    return real_app(kb_settings, FakeModelProvider(), FakeClock())[0]


def converse(client: TestClient, texts: list[str]) -> str:
    """One caller conversation of several messages; returns the caller's secret id."""
    cid = client.post("/conversations").json()["conversationId"]
    for text in texts:
        sent = client.post(f"/conversations/{cid}/messages", json={"text": text})
        assert sent.status_code == 200
    return cid


def close_idle(client: TestClient, settings: Settings, cid: str) -> str:
    """Age the conversation past the limit and let one real list read close it."""
    age(settings, cid, settings.IDLE_CLOSE_MINUTES + 1)
    assert client.get("/conversations").status_code == 200
    return row(settings, cid)[3]


def run_export(client: TestClient, out: Path) -> int:
    return export.main(["http://testserver", "--out", str(out)], client=client)


def without_ids(text: str, *ids: str) -> str:
    # The random hex ids can hold a long run of digits by chance; drop them first.
    for value in ids:
        text = text.replace(value, "")
    return text


def test_list_is_newest_first_with_outcome(kb_settings: Settings):
    model = FakeModelProvider(results=recorded() + recorded() + recorded())
    client, _ = real_app(kb_settings, model, FakeClock())
    cids = [converse(client, [QUESTION]) for _ in range(3)]
    for cid in cids:
        age(kb_settings, cid, kb_settings.IDLE_CLOSE_MINUTES + 1)

    listed = client.get("/conversations").json()["conversations"]

    shown = [(c["startedAt"], c["intent"], c["outcome"]) for c in listed]
    print("listed (startedAt, intent, outcome):", shown)
    publics = [row(kb_settings, cid)[3] for cid in cids]
    assert [c["publicId"] for c in listed] == publics[::-1]
    starts = [c["startedAt"] for c in listed]
    assert starts == sorted(starts, reverse=True)
    assert all(c["startedAt"] and c["intent"] and c["outcome"] for c in listed)


def test_fee_conversation_detail(kb_settings: Settings):
    client, _ = real_app(
        kb_settings, FakeModelProvider(results=recorded()), FakeClock()
    )
    cid = converse(client, [QUESTION])
    public = row(kb_settings, cid)[3]

    detail = client.get(f"/conversations/{public}").json()

    summary, (turn,) = detail["summary"], detail["turns"]
    tools = [t["name"] for t in turn["toolsCalled"]]
    print(
        "turnCount", summary["turnCount"], "| callerText", turn["callerText"],
        "| latencyMs", turn["latencyMs"], "| costUsd", summary["costUsd"],
        "| tools", tools,
    )  # fmt: skip
    assert summary["turnCount"] == 1
    assert turn["callerText"] == QUESTION
    assert turn["latencyMs"] is not None
    assert summary["costUsd"] > 0
    assert "search_knowledge" in tools


def test_draft_lands_through_the_export_command(
    client: TestClient, kb_settings: Settings, tmp_path: Path
):
    sent = ["Hi, my AC is blowing warm air", "Can someone come tomorrow?"]
    cid = converse(client, sent)
    public = close_idle(client, kb_settings, cid)
    assert client.post(f"/conversations/{public}/eval-candidate").status_code == 201
    out = tmp_path / "eval" / "candidates"

    code = run_export(client, out)

    file = out / f"CAND-{public[:8]}.json"
    draft = json.loads(file.read_text())
    print(
        "exit", code, "| files", sorted(p.name for p in out.iterdir()),
        "| callerMessages", draft["callerMessages"], "| expected", draft["expected"],
        "| observed", draft["observed"],
    )  # fmt: skip
    assert code == 0
    assert draft["callerMessages"] == sent
    assert draft["expected"] == EMPTY_EXPECTED
    assert draft["observed"]["outcome"] == "failed"
    first = file.read_bytes()
    assert run_export(client, out) == 0
    print("second run same bytes:", file.read_bytes() == first)
    assert file.read_bytes() == first


def test_card_number_never_reaches_the_exported_file(
    client: TestClient, kb_settings: Settings, tmp_path: Path
):
    cid = converse(client, ["My card is 4111 1111 1111 1111"])
    public = close_idle(client, kb_settings, cid)
    assert client.post(f"/conversations/{public}/eval-candidate").status_code == 201
    out = tmp_path / "eval" / "candidates"

    assert run_export(client, out) == 0

    text = (out / f"CAND-{public[:8]}.json").read_text()
    stripped = without_ids(text, public)
    run = re.search(r"\d{13,19}", stripped)
    print(
        "callerMessages", json.loads(text)["callerMessages"],
        "| 13-19 digit run:", run.group(0) if run else None, "| '4111' in file:", "4111" in text,
    )  # fmt: skip
    assert json.loads(text)["callerMessages"] == ["My card is [card number removed]"]
    assert not run and not CARD_RUN.search(stripped)
    assert "4111" not in text


def test_idle_conversation_listed_with_outcome_and_no_secret_ids(
    client: TestClient, kb_settings: Settings
):
    idle = play(client, "Is my AC compressor covered by warranty?")
    fresh = play(client, "Are you open on Sundays?")
    age(kb_settings, idle, kb_settings.IDLE_CLOSE_MINUTES + 1)

    listing = client.get("/conversations")

    by_public = {c["publicId"]: c for c in listing.json()["conversations"]}
    idle_public, fresh_public = row(kb_settings, idle)[3], row(kb_settings, fresh)[3]
    shown = {
        "idle": (by_public[idle_public]["outcome"], by_public[idle_public]["outcomeReason"]),
        "fresh": (by_public[fresh_public]["outcome"], by_public[fresh_public]["outcomeReason"]),
    }  # fmt: skip
    details = [client.get(f"/conversations/{p}").text for p in by_public]
    print("one GET /conversations:", shown)
    assert shown["idle"] == ("failed", "idle_unresolved")
    assert shown["fresh"] == (None, None)
    for text in [listing.text, *details]:
        assert idle not in text and fresh not in text
    print("secret ids in list or details:", False)


def test_flag_on_unknown_public_id_is_404(client: TestClient, kb_settings: Settings):
    cid = play(client, "Are you open on Sundays?")
    unknown = "0123456789abcdef" * 2
    assert unknown != row(kb_settings, cid)[3]

    answers = [
        client.post(f"/conversations/{target}/flag", json={"note": "x"})
        for target in (unknown, cid)
    ]

    with closing(sqlite3.connect(kb_settings.APP_DB_PATH)) as db:
        flags = db.execute("SELECT COUNT(*) FROM flags").fetchone()[0]
    print([(a.status_code, a.json()["error"]) for a in answers], "| flags:", flags)
    for answer in answers:
        assert answer.status_code == 404
        assert answer.json()["error"] == "conversation_not_found"
    assert flags == 0


def test_five_card_messages_stay_out_of_list_detail_flag_and_draft(
    client: TestClient, kb_settings: Settings, tmp_path: Path
):
    cid = converse(client, CARDS)
    public = close_idle(client, kb_settings, cid)
    flagged = client.post(
        f"/conversations/{public}/flag", json={"note": "4111 1111 1111 1111 was quoted"}
    )
    assert flagged.status_code == 201
    assert client.post(f"/conversations/{public}/eval-candidate").status_code == 201
    out = tmp_path / "out"
    assert run_export(client, out) == 0

    texts = {
        "list": client.get("/conversations").text,
        "detail": client.get(f"/conversations/{public}").text,
        "admin": client.get("/admin/eval-candidates", headers=ADMIN).text,
        "file": (out / f"CAND-{public[:8]}.json").read_text(),
    }

    with closing(sqlite3.connect(kb_settings.APP_DB_PATH)) as db:
        (note,) = db.execute("SELECT note FROM flags").fetchone()
    found = {
        place: bool(
            re.search(r"\d{13,19}", without_ids(t, public, cid))
            or CARD_RUN.search(without_ids(t, public, cid))
        )
        for place, t in texts.items()
    }
    print("card-shaped run found:", found, "| stored flag note:", note)
    assert not any(found.values())
    assert note == "[card number removed] was quoted" and not CARD_RUN.search(note)


def set_customer(settings: Settings, cid: str, customer_id: str) -> None:
    with closing(sqlite3.connect(settings.APP_DB_PATH)) as db, db:
        db.execute(
            "UPDATE conversations SET customer_id = ? WHERE id = ?", (customer_id, cid)
        )


def test_draft_and_detail_hold_only_their_own_customer(
    client: TestClient, kb_settings: Settings, tmp_path: Path
):
    a = converse(client, ["I want to book a tune-up"])
    b = converse(client, ["My furnace is making a noise"])
    set_customer(kb_settings, a, "MHC-52445")
    set_customer(kb_settings, b, "MHC-38140")
    a_public = close_idle(client, kb_settings, a)
    close_idle(client, kb_settings, b)
    assert client.post(f"/conversations/{a_public}/eval-candidate").status_code == 201
    out = tmp_path / "out"
    assert run_export(client, out) == 0

    detail = client.get(f"/conversations/{a_public}")

    draft_text = (out / f"CAND-{a_public[:8]}.json").read_text()
    admin_draft = next(
        c["scenario"]
        for c in client.get("/admin/eval-candidates", headers=ADMIN).json()[
            "candidates"
        ]
        if c["scenarioId"] == f"CAND-{a_public[:8]}"
    )
    summary = detail.json()["summary"]
    print(
        "A detail customer:", summary["customerName"],
        "| A draft customerId:", json.loads(draft_text)["customerId"],
    )  # fmt: skip
    assert summary["customerName"] == "Michael Chen"
    assert json.loads(draft_text)["customerId"] == "MHC-52445"
    for text in (detail.text, draft_text, json.dumps(admin_draft)):
        for other in ("MHC-38140", "Maria Johnson", "512-292-7955", b):
            assert other not in text
    secret = client.post(f"/conversations/{a}/eval-candidate")
    assert secret.status_code == 404
    assert secret.json()["error"] == "conversation_not_found"
