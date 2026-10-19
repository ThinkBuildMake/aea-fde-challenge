"""Opt-in live check of criterion 1 (set MERIDIAN_LIVE_TESTS=1 to run)."""

import os

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.llm import FakeModelProvider
from app.main import create_app
from app.settings import Settings

pytestmark = pytest.mark.skipif(
    os.environ.get("MERIDIAN_LIVE_TESTS") != "1"
    or not os.environ.get("OPENROUTER_API_KEY"),
    reason="live tests need MERIDIAN_LIVE_TESTS=1 and OPENROUTER_API_KEY",
)


def test_overview_reads_real_key_usage(started: Settings):
    settings = started.model_copy(
        update={"OPENROUTER_API_KEY": SecretStr(os.environ["OPENROUTER_API_KEY"])}
    )
    response = TestClient(create_app(settings, model=FakeModelProvider())).get(
        "/overview"
    )
    assert response.status_code == 200
    spend = response.json()["spend"]
    total = spend["totalUsd"]
    assert isinstance(total, (int, float)) and not isinstance(total, bool)
    assert total >= 0
    assert spend["alertUsd"] == 100
    print(f"live total spend USD: {total}, alert: {spend['alert']}")
