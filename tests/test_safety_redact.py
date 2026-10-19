import re

import pytest

from app.safety.service import redact_card_numbers

DIGIT_RUN = re.compile(r"\d(?:[\s.\-\u2010-\u2015\u2212/,_]*\d){12,}")


def test_spaced_card_is_removed() -> None:
    r = redact_card_numbers("My card is 4111 1111 1111 1111")
    assert DIGIT_RUN.search(r.text) is None
    assert r.removed is True


@pytest.mark.parametrize(
    "text",
    [
        "4111-1111-1111-1111",
        "4111111111111111",
        "4111  1111 1111 1111",
        "4111 - 1111 - 1111 - 1111",
        "4111\t1111\t1111\t1111",
        "4111    1111    1111    1111",
        "4111\n1111\n1111\n1111",
        "4111.1111.1111.1111",
        "4111 -  1111\t\t1111  1111",
        "3782 822463 10005",
        "6011000990139424123",
        "4111\u20131111\u20131111\u20131111",
        "4111 \u2014 1111 \u2014 1111 \u2014 1111",
        "4111/1111/1111/1111",
        "4111,1111,1111,1111",
        "4111_1111_1111_1111",
        "4111\u22121111\u22121111\u22121111",
        "4111\u00a01111\u00a01111\u00a01111",
        "\uff14\uff11\uff11\uff11 \uff11\uff11\uff11\uff11 \uff11\uff11\uff11\uff11 \uff11\uff11\uff11\uff11",
        "\u0664\u0661\u0661\u0661\u0661\u0661\u0661\u0661\u0661\u0661\u0661\u0661\u0661\u0661\u0661\u0661",
        "4111 1111 1111 1111 12/28 123",
        "4111 - 1111 - 1111 - 1111 exp 12/28",
        "4111, 1111, 1111, 1111",
        "4111-1111 1111-1111",
        "378282246310005",
    ],
)
def test_other_formats_removed_and_stable(text: str) -> None:
    a = redact_card_numbers(text)
    b = redact_card_numbers(text)
    assert DIGIT_RUN.search(a.text) is None
    assert DIGIT_RUN.search(b.text) is None
    assert a.text == b.text
    assert a.removed is True


def test_phone_number_stays() -> None:
    r = redact_card_numbers("Call me at 512-555-0101 about INV-204411")
    assert r.text == "Call me at 512-555-0101 about INV-204411"
    assert r.removed is False


@pytest.mark.parametrize(
    "text",
    [
        "Call 512-555-0102",
        "The repair was $1,200 and the visit $89.",
        "Book me for 2026/10/21 please",
        "INV-204411 and account MHC-10002",
        "Prices: $89, $245, $144",
        "Account MHC-10002, 512-555-0102",
        "512-555-0102, 4412 Oak Hollow Dr",
        "MHC-10002 512-555-0102",
        "Daniel Reyes 512-555-0104 4412 Oak Hollow",
        "512-555-0102 / 512-555-0199",
        "$1,200 and $3,400, 512-555-0102",
        "Omar Patel, MHC-10002, 512-555-0102, 901 Brookside Ct",
    ],
)
def test_ordinary_numbers_stay(text: str) -> None:
    r = redact_card_numbers(text)
    assert r.text == text
    assert r.removed is False
