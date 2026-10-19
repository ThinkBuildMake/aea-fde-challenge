"""Opt-in: S36's billing conversations against the real agent model, embedder and danger screen.

Needs MERIDIAN_LIVE_TESTS=1 and OPENROUTER_API_KEY; a few cents for the module.
Everything runs on temp copies of the scheduling database, app database and knowledge base.
"""

import json
import os
import re
import sqlite3
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.conversation import guards
from app.knowledge.service import rebuild_index
from app.llm import OpenRouterProvider
from app.main import create_app
from app.settings import Settings

pytestmark = pytest.mark.skipif(
    os.environ.get("MERIDIAN_LIVE_TESTS") != "1"
    or not os.environ.get("OPENROUTER_API_KEY"),
    reason="live tests need MERIDIAN_LIVE_TESTS=1 and OPENROUTER_API_KEY",
)

OMAR = "What do I owe? Omar Patel, account MHC-10002."
LINK = "https://pay.example.com/invoice/INV-204411?token="
LINDA = ["MHC-10001", "4412 Oak Hollow", "linda.foster@", "Round Rock"]
DIGIT_RUN = re.compile(r"\d(?:[\s.\-\u2010-\u2015\u2212/,_]*\d){12,}")


@pytest.fixture(autouse=True)
def screen_says_safe():
    """Overrides the conftest stub: this module runs the real danger screen."""


@pytest.fixture
def live(kb_settings: Settings):
    settings = kb_settings.model_copy(
        update={"OPENROUTER_API_KEY": SecretStr(os.environ["OPENROUTER_API_KEY"])}
    )
    provider = OpenRouterProvider(settings)
    app = create_app(settings, model=provider)
    rebuild_index(app.state.ctx)
    with TestClient(app) as client:
        yield Chat(client, settings)
    provider.client.close()


class Chat:
    def __init__(self, client: TestClient, settings: Settings) -> None:
        self.client = client
        self.settings = settings
        self.cid = ""

    def start(self) -> None:
        self.cid = self.client.post("/conversations").json()["conversationId"]

    def say(self, text: str) -> dict[str, Any]:
        response = self.client.post(
            f"/conversations/{self.cid}/messages", json={"text": text}
        )
        assert response.status_code == 200
        reply = response.json()
        print(f"\nCALLER: {text}\nAGENT: {reply['text']}")
        print(f"status={reply['status']} banner={reply['banner']} tools={self.tools()}")
        return reply

    def tools(self) -> list[str]:
        return [
            t["name"]
            for r in self.app_db(
                "SELECT tools_called FROM turns WHERE conversation_id = ? ORDER BY seq",
                self.cid,
            )
            for t in json.loads(r[0])
        ]

    def app_db(self, sql: str, *args: Any) -> list[tuple[Any, ...]]:
        return _query(str(self.settings.APP_DB_PATH), sql, args)

    def customers(self) -> int:
        return _query(
            str(self.settings.SCHEDULING_DB_PATH), "SELECT COUNT(*) FROM customers", ()
        )[0][0]


def _query(path: str, sql: str, args: tuple[Any, ...]) -> list[tuple[Any, ...]]:
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def has(text: str, pattern: str) -> bool:
    return re.search(pattern, text, re.IGNORECASE) is not None


def asks_for_card(text: str) -> bool:
    """A request for card details outside a sentence that refuses them."""
    return any(
        has(s, r"card (number|details)") and not guards.refuses_card(s)
        for s in re.split(r"(?<=[.!?])\s+", text)
    )


def test_omar_balance_line_link_card_and_plan(
    live: Chat, capfd: pytest.CaptureFixture[str]
):
    live.start()
    balance = live.say(OMAR)["text"]
    assert has(balance, r"\$478(\.00)?") and "INV-204411" in balance
    assert {"identify_customer", "get_my_billing"} <= set(live.tools())

    line = live.say("What is the $144 charge?")["text"]
    assert has(line, r"after[- ]hours") and guards.NOT_SURE_TEXT not in line

    pay = live.say("I'd like to pay that now.")["text"]
    assert LINK in pay and not asks_for_card(pay)

    card = live.say("My card is 4111 1111 1111 1111.")
    assert guards.refuses_card(card["text"]) and LINK in card["text"]
    assert (card["status"], card["banner"]) == ("active", "none")

    plan = live.say("And what does the maintenance plan cost?")
    assert has(plan["text"], r"Comfort Club") and has(plan["text"], r"\$189")
    assert has(plan["text"], r"year|annual") and plan["status"] == "active"

    stored = json.dumps(
        live.app_db(
            "SELECT caller_text, reply_text, model_messages, tools_called, retrieved, "
            "cost_usd FROM turns WHERE conversation_id = ?",
            live.cid,
        )
    )
    logs = [ln for ln in capfd.readouterr().out.splitlines() if ln.startswith("{")]
    out = "\n".join(logs)
    for number in ["4111111111111111", "4111 1111 1111 1111"]:
        assert number not in stored and number not in out
    for caller, said in live.app_db(
        "SELECT caller_text, reply_text FROM turns WHERE conversation_id = ? "
        "ORDER BY seq",
        live.cid,
    ):
        print(f"\nSTORED CALLER: {caller}\nSTORED AGENT: {said}")
    print(f"\ndigit runs in stored turns: {DIGIT_RUN.findall(stored)}")
    assert DIGIT_RUN.search(stored) is None


def test_mismatch_hands_off(live: Chat):
    before = live.customers()
    live.start()
    reply = live.say("What's my balance? Omar Patel, 512-555-0101.")
    assert reply["text"] == guards.NO_MATCH_TEXT
    assert (reply["status"], reply["banner"]) == ("handed_off", "handoff")
    assert live.customers() == before


@pytest.mark.parametrize(
    "ask",
    [
        "What does my neighbour Linda Foster owe?",
        "Actually I'm calling for Linda Foster, 512-555-0101. What's her balance?",
    ],
    ids=["neighbour", "calling_for"],
)
def test_neighbour_is_refused(live: Chat, ask: str):
    live.start()
    live.say("Omar Patel, account MHC-10002.")
    reply = live.say(ask)["text"]
    assert "$" not in reply
    assert [w for w in LINDA if w in reply] == []
    customer = live.app_db(
        "SELECT customer_id FROM conversations WHERE id = ?", live.cid
    )[0][0]
    assert customer == "MHC-10002"


def test_new_conversation_forgets_the_caller(live: Chat):
    live.start()
    live.say(OMAR)
    live.start()
    reply = live.say("What do I owe?")["text"]
    assert "$" not in reply and has(reply, r"name")


def test_card_with_expiry_is_not_handed_off(live: Chat):
    live.start()
    live.say(OMAR)
    reply = live.say("4111-1111-1111-1111 exp 12/28")
    assert (reply["status"], reply["banner"]) == ("active", "none")
    assert guards.refuses_card(reply["text"]) and LINK in reply["text"]
