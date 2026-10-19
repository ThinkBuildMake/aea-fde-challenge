"""SC-1: five conversations at once stay within 1.5× the single-conversation p95,
and /health keeps answering within 1 s while they run."""

import threading
import time
from collections.abc import Iterator

import httpx2
import pytest
import uvicorn

from app.llm import FakeModelProvider
from app.main import create_app
from app.settings import Settings
from tests.gate.harness import CaseResult, evaluate_pf1, evaluate_sc1

TURNS = 5
LIFTED = {"NEW_CONVERSATIONS_PER_HOUR": 10**6, "MESSAGES_PER_MINUTE": 10**6}


@pytest.fixture
def live_url(started: Settings) -> Iterator[str]:
    app = create_app(
        started.model_copy(update=LIFTED), model=FakeModelProvider(delay_s=0.2)
    )
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started:
        assert time.monotonic() < deadline, "server did not start"
        time.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


def conversation(url: str) -> list[int]:
    """One conversation of TURNS messages; the wall-clock ms of each reply."""
    latencies = []
    with httpx2.Client(base_url=url, timeout=30) as client:
        cid = client.post("/conversations").json()["conversationId"]
        for n in range(TURNS):
            started = time.perf_counter()
            response = client.post(
                f"/conversations/{cid}/messages", json={"text": f"message {n}"}
            )
            latencies.append(round((time.perf_counter() - started) * 1000))
            assert response.status_code == 200
    return latencies


def test_five_simultaneous_conversations_stay_fast(live_url: str):
    polls: list[tuple[int, float]] = []
    done = threading.Event()

    def poll_health() -> None:
        with httpx2.Client(base_url=live_url, timeout=5) as client:
            while not done.is_set():
                started = time.perf_counter()
                status = client.get("/health").status_code
                polls.append((status, time.perf_counter() - started))
                time.sleep(0.05)

    poller = threading.Thread(target=poll_health)
    poller.start()
    try:
        single_runs = [conversation(live_url) for _ in range(2)]
        barrier = threading.Barrier(5)
        concurrent: list[list[int]] = []

        def worker() -> None:
            barrier.wait()
            concurrent.append(conversation(live_url))

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        done.set()
        poller.join()

    single = [ms for run in single_runs for ms in run]
    verdict = evaluate_sc1(single, [ms for run in concurrent for ms in run])
    pf1 = evaluate_pf1(
        [CaseResult(f"single-{i}", run[0]) for i, run in enumerate(single_runs)]
    )
    slowest = max(seconds for _, seconds in polls)
    print(verdict.message)
    print(
        f"/health: {len(polls)} polls, slowest {slowest * 1000:.0f} ms, statuses {sorted({s for s, _ in polls})}"
    )
    print(pf1.message)
    assert len(concurrent) == 5
    assert verdict.passed, verdict.message
    assert len(polls) >= 10
    assert all(status == 200 for status, _ in polls)
    assert slowest < 1.0
    assert pf1.passed, pf1.message


def test_sc1_fails_when_concurrent_p95_too_slow():
    verdict = evaluate_sc1(single_ms=[200] * 10, concurrent_ms=[200] * 20 + [400] * 5)

    assert verdict.passed is False
    assert "SC-1" in verdict.message and "1.5×" in verdict.message
