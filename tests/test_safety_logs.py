import dataclasses
import json
import logging
import re
import sys

import httpx2
import pytest

from app.main import create_app
from app.safety.service import (
    OpenRouterSafetyClassifier,
    ScreenUnavailable,
    redact_card_numbers,
    screen_safety,
)
from app.settings import Settings

KEY = "fake-openrouter-key-for-log-test"
DIGIT_RUN = re.compile(r"\d(?:[ -]?\d){12,18}")


def _ok(request: httpx2.Request) -> httpx2.Response:
    content = json.dumps({"verdict": "emergency", "reason": "gas"})
    return httpx2.Response(
        200,
        json={
            "id": "x",
            "object": "chat.completion",
            "created": 0,
            "model": "m",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": content},
                }
            ],
        },
    )


def _timeout(request: httpx2.Request) -> httpx2.Response:
    raise httpx2.ReadTimeout("slow", request=request)


def test_logs_hold_no_message_text(
    tmp_settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    root = logging.getLogger()
    handler = logging.StreamHandler(sys.stdout)
    old_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    try:
        base = create_app(tmp_settings).state.ctx
        red = redact_card_numbers("My card is 4111 1111 1111 1111 and I smell gas")
        for h in (_ok, _timeout):
            clf = OpenRouterSafetyClassifier(
                KEY, "m", http_client=httpx2.Client(transport=httpx2.MockTransport(h))
            )
            ctx = dataclasses.replace(base, safety=clf)
            try:
                screen_safety(ctx, red.text, [], False)
            except ScreenUnavailable:
                pass
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)
    out = capsys.readouterr().out
    assert DIGIT_RUN.search(out) is None
    assert "My card is" not in out
    assert "smell gas" not in out
    assert KEY not in out
    events = [
        json.loads(line)["event"] for line in out.splitlines() if line.startswith("{")
    ]
    assert "safety_screen" in events
    assert "safety_screen_failed" in events
