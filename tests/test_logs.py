import json
import re

import pytest

from app.logs import log_event

DIGIT_RUN = re.compile(r"\d(?:[ \t-]{0,3}\d){12,18}")


def test_log_event_masks_digit_runs(capsys: pytest.CaptureFixture[str]) -> None:
    log_event("x", note="4111 1111 1111 1111", other="4111-1111-1111-1111", n=5)
    log_event("x", a="4111  1111 1111 1111", b="4111 - 1111 - 1111 - 1111")
    out = capsys.readouterr().out
    assert DIGIT_RUN.search(out) is None
    data = json.loads(out.splitlines()[0])
    assert data["n"] == 5
    assert data["event"] == "x"


def test_log_event_is_one_json_line(capsys: pytest.CaptureFixture[str]) -> None:
    log_event("hello", ok=True, ms=1.5, none=None, text="plain")
    out = capsys.readouterr().out
    assert out.count("\n") == 1
    assert json.loads(out) == {
        "event": "hello",
        "ok": True,
        "ms": 1.5,
        "none": None,
        "text": "plain",
    }
