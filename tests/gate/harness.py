"""Plays the gate's eval conversation through the app and judges first-reply time (PF-1)."""

import math
from dataclasses import dataclass
from typing import Any

from fastapi.testclient import TestClient


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@dataclass
class CaseResult:
    scenario_id: str
    first_reply_ms: int


@dataclass
class GateVerdict:
    passed: bool
    p95_ms: int
    message: str


def play_case(client: TestClient, case: dict[str, Any], clock: FakeClock) -> CaseResult:
    conversation_id = client.post("/conversations").json()["conversationId"]
    started = clock.monotonic()
    response = client.post(
        f"/conversations/{conversation_id}/messages", json={"text": case["opening"]}
    )
    assert response.status_code == 200
    return CaseResult(case["id"], round((clock.monotonic() - started) * 1000))


def p95(values: list[int]) -> int:
    """Nearest-rank 95th percentile."""
    ordered = sorted(values)
    return ordered[max(math.ceil(0.95 * len(ordered)) - 1, 0)]


def evaluate_pf1(results: list[CaseResult], limit_ms: int = 6000) -> GateVerdict:
    value = p95([r.first_reply_ms for r in results])
    passed = value <= limit_ms
    message = (
        f"PF-1: p95 time to first visible reply ≤ 6 s; measured {value} ms "
        f"over {len(results)} case(s): {'ok' if passed else 'FAILED'}"
    )
    return GateVerdict(passed, value, message)


def evaluate_pf2(latencies_ms: list[int], limit_ms: int = 10000) -> GateVerdict:
    value = p95(latencies_ms)
    passed = value <= limit_ms
    message = (
        f"PF-2: p95 time for a turn with tool calls ≤ 10 s; measured {value} ms "
        f"over {len(latencies_ms)} turn(s): {'ok' if passed else 'FAILED'}"
    )
    return GateVerdict(passed, value, message)
