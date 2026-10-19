import json
import os

from fastapi.testclient import TestClient

from app.llm import FakeModelProvider
from app.main import create_app
from app.settings import Settings
from tests.conftest import REPO
from tests.gate.harness import FakeClock, evaluate_pf1, play_case

CASE = json.loads((REPO / "eval" / "gate" / "GATE-PF1.json").read_text())


def run_gate_case(settings: Settings, delay_s: float):
    clock = FakeClock()
    model = FakeModelProvider(delay_s=delay_s, sleep=clock.advance)
    client = TestClient(create_app(settings, model=model, clock=clock))
    return evaluate_pf1([play_case(client, CASE, clock)])


def test_gate_case_first_reply(started: Settings):
    verdict = run_gate_case(started, float(os.environ.get("GATE_FAKE_DELAY_S", "0")))
    assert verdict.passed, verdict.message


def test_gate_fails_on_slow_first_reply(started: Settings):
    verdict = run_gate_case(started, 7.0)
    assert verdict.passed is False
    assert verdict.p95_ms >= 7000
    assert "PF-1" in verdict.message and "6 s" in verdict.message
