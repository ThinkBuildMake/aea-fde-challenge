import json
import re

import pytest

from app.logs import log_event

DIGIT_RUN = re.compile(r"\d(?:[\s.\-\u2010-\u2015\u2212/,_]*\d){12,}")


def test_log_event_masks_digit_runs(capsys: pytest.CaptureFixture[str]) -> None:
    log_event("x", note="4111 1111 1111 1111", other="4111-1111-1111-1111", n=5)
    log_event("x", a="4111  1111 1111 1111", b="4111 - 1111 - 1111 - 1111")
    log_event("x", c="4111    1111    1111    1111", d="4111\n1111\n1111\n1111")
    log_event("x", e="4111.1111.1111.1111", f="4111 -  1111\t\t1111  1111")
    log_event("x", g="4111\u20131111\u20131111\u20131111", h="4111/1111/1111/1111")
    log_event("x", i="4111,1111,1111,1111", j="4111_1111_1111_1111")
    out = capsys.readouterr().out
    values = [str(v) for line in out.splitlines() for v in json.loads(line).values()]
    assert not [v for v in values if DIGIT_RUN.search(v)]
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


def test_log_event_keeps_ordinary_numbers(capsys: pytest.CaptureFixture[str]) -> None:
    log_event("x", phone="512-555-0102", price="$1,200", day="2026/10/21")
    data = json.loads(capsys.readouterr().out)
    assert (data["phone"], data["price"], data["day"]) == (
        "512-555-0102",
        "$1,200",
        "2026/10/21",
    )
