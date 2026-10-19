import json

import httpx2
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.llm import FakeModelProvider
from app.main import create_app
from app.monitoring.spend import KeyUsageUnavailable, OpenRouterKeyUsage
from app.settings import Settings
from tests.gate.harness import FakeClock


class Fixed:
    def __init__(self, usd: float) -> None:
        self.usd = usd
        self.calls = 0

    def read(self) -> float:
        self.calls += 1
        return self.usd


class Failing:
    def read(self) -> float:
        raise RuntimeError("provider down")


def overview(settings: Settings, reader, clock=None) -> dict:
    app = create_app(settings, model=FakeModelProvider(), clock=clock, key_usage=reader)
    response = TestClient(app).get("/overview")
    assert response.status_code == 200
    return response.json()


def co1(body: dict) -> dict:
    return next(g for g in body["guarantees"] if g["key"] == "CO-1")


def test_unreadable_usage_leaves_rest_of_overview(started, capsys):
    body = overview(started, Failing())
    assert body["spend"] == {"totalUsd": None, "alertUsd": 100, "alert": False}
    assert co1(body)["status"] == "no_data"
    for field in ("status", "success", "volume", "guarantees", "latencySeries24h"):
        assert body[field] is not None
    lines = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if "spend_read_failed" in line
    ]
    assert lines == [{"event": "spend_read_failed", "error": "RuntimeError"}]
    print("spend", body["spend"], "log", lines)


def test_openai_line_is_added(started):
    settings = started.model_copy(update={"OPENAI_SPEND_USD": 2.5})
    body = overview(settings, Fixed(40.0))
    assert body["spend"]["totalUsd"] == pytest.approx(42.5)
    print("spend", body["spend"])


def test_flag_on_past_line(started):
    body = overview(started, Fixed(104.0))
    assert body["spend"] == {"totalUsd": 104.0, "alertUsd": 100, "alert": True}
    print("spend", body["spend"])


def test_flag_off_below_line(started):
    body = overview(started, Fixed(38.0))
    assert body["spend"]["alert"] is False
    print("spend", body["spend"])


def test_usage_read_once_a_minute(started):
    reader, clock = Fixed(10.0), FakeClock()
    client = TestClient(
        create_app(started, model=FakeModelProvider(), clock=clock, key_usage=reader)
    )
    for _ in range(5):
        assert client.get("/overview").status_code == 200
        clock.advance(10)
    assert reader.calls == 1
    clock.advance(20)
    client.get("/overview")
    assert reader.calls == 2
    print("reads after 5 calls: 1; after a minute passes:", reader.calls)


@pytest.mark.parametrize(
    ("usd", "alert", "status"),
    [(100.0, True, "breach"), (104.0, True, "breach"), (38.0, False, "ok")],
)
def test_co1_guard_at_and_over_line(started, usd, alert, status):
    body = overview(started, Fixed(usd))
    assert body["spend"]["alert"] is alert
    assert co1(body)["status"] == status
    assert co1(body)["limit"] == 100


def reader_over(started: Settings, handler) -> OpenRouterKeyUsage:
    settings = started.model_copy(update={"OPENROUTER_API_KEY": SecretStr("sk-test")})
    return OpenRouterKeyUsage(
        settings, httpx2.Client(transport=httpx2.MockTransport(handler))
    )


def test_key_usage_sums_credits_and_byok(started):
    seen = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json={"data": {"usage": 19.5, "byok_usage": 68.25}})

    assert reader_over(started, handler).read() == 87.75
    assert seen[0].method == "GET"
    assert str(seen[0].url).endswith("/api/v1/key")
    assert seen[0].headers["authorization"] == "Bearer sk-test"


def test_key_usage_errors_raise(started):
    for response in (
        httpx2.Response(500),
        httpx2.Response(200, json={"data": {}}),
    ):
        with pytest.raises(KeyUsageUnavailable):
            reader_over(started, lambda request, r=response: r).read()
