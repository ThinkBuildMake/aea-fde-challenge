import re

import pytest

from app.safety.service import redact_card_numbers

DIGIT_RUN = re.compile(r"\d(?:[ -]?\d){12,18}")


def test_spaced_card_is_removed() -> None:
    r = redact_card_numbers("My card is 4111 1111 1111 1111")
    assert DIGIT_RUN.search(r.text) is None
    assert r.removed is True


@pytest.mark.parametrize("text", ["4111-1111-1111-1111", "4111111111111111"])
def test_other_formats_removed_and_stable(text: str) -> None:
    a = redact_card_numbers(text)
    b = redact_card_numbers(text)
    assert DIGIT_RUN.search(a.text) is None
    assert DIGIT_RUN.search(b.text) is None
    assert a.text == b.text
    assert a.removed is True


def test_phone_number_stays() -> None:
    r = redact_card_numbers("Call me at 512-555-0101")
    assert r.text == "Call me at 512-555-0101"
    assert r.removed is False
