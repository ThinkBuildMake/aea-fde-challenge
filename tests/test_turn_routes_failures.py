"""One turn at a time per conversation, and the demo outage switch on sendMessage."""

import threading

from app.conversation import guards
from app.llm import FakeModelProvider, ModelResult
from app.settings import Settings
from tests.test_turn import client_for, new_conversation, rows, say


class Gated(FakeModelProvider):
    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def complete(self, messages, *, tools=None, timeout_s) -> ModelResult:
        self.entered.set()
        assert self.release.wait(10)
        return super().complete(messages, tools=tools, timeout_s=timeout_s)


def test_a_second_message_while_one_is_answered_is_turn_in_progress(started: Settings):
    model = Gated()
    client = client_for(started, model)
    cid = new_conversation(client)
    first: list = []
    worker = threading.Thread(
        target=lambda: first.append(
            client.post(f"/conversations/{cid}/messages", json={"text": "one"})
        )
    )
    worker.start()
    assert model.entered.wait(5)
    second = client.post(f"/conversations/{cid}/messages", json={"text": "two"})
    print(second.status_code, second.json())
    assert second.status_code == 409 and second.json()["error"] == "turn_in_progress"
    model.release.set()
    worker.join(10)
    assert first[0].status_code == 200
    assert len(rows(started, "SELECT * FROM turns")) == 1
    assert say(client, cid, "three")["banner"] == "none"


def test_the_outage_switch_skips_the_model_when_allowed(started: Settings):
    model = FakeModelProvider()
    client = client_for(
        started.model_copy(update={"DEMO_FAULT_INJECTION": True}), model
    )
    cid = new_conversation(client)
    reply = client.post(
        f"/conversations/{cid}/messages", json={"text": "hi", "simulateOutage": True}
    ).json()
    print(len(model.received), reply["text"][:30], reply["banner"], reply["actions"])
    assert model.received == []
    assert reply["text"] == guards.FALLBACK_TEXT and reply["banner"] == "error"
    assert "request_callback" in reply["actions"]
    turn = rows(started, "SELECT * FROM turns")[0]
    assert turn["fallback_used"] == 1 and turn["error"] == "provider_error"


def test_the_outage_switch_is_ignored_when_off(started: Settings):
    model = FakeModelProvider(replies=["Hello."])
    client = client_for(started, model)
    start = client.post("/conversations").json()
    assert start["demoFaults"] is False
    reply = client.post(
        f"/conversations/{start['conversationId']}/messages",
        json={"text": "hi", "simulateOutage": True},
    ).json()
    print(len(model.received), reply["text"], reply["banner"])
    assert len(model.received) == 1 and reply["text"] == "Hello."
    assert reply["banner"] == "none"
    assert rows(started, "SELECT fallback_used FROM turns")[0][0] == 0
