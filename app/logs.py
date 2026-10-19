import json
import re
import sys

# 13+ digits with any whitespace, dot, dash, slash, comma or underscore between them,
# not starting inside a money figure or a formatted number ($3,400).
DIGIT_RUN = re.compile(
    r"(?<!\d)(?<!\$)(?<!\d[,.])\d(?:[\s.\-\u2010-\u2015\u2212/,_]*\d){12,}(?!\d)"
)
_GROUPS = re.compile(r"(\d+)(\D*)")


def _kind(separator: str) -> str | None:
    """Whitespace is one kind; one punctuation mark is its own kind, padded with
    whitespace (" - ") a different one; anything else is None and never joins."""
    if separator.isspace():
        return " "
    mark = "".join(separator.split())
    if len(mark) != 1:
        return None
    return mark if mark == separator else f" {mark}"


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch) * (2 if i % 2 else 1)
        total += d - 9 if d > 9 else d
    return total % 10 == 0


def _card_spans(run: str) -> list[tuple[int, int]]:
    """The parts of a digit run that are taken as a card number.

    The whole run counts when it has 13-19 digits that pass the Luhn check. Otherwise
    each segment whose groups are joined by one kind of separator counts when it has
    13+ digits joined by whitespace or a bare mark, or 13-19 digits that pass Luhn.
    So "512-555-0102, 4412" (a phone, then a house number) is left alone."""
    found = list(_GROUPS.finditer(run))
    spans = [(m.start(1), m.end(1)) for m in found]
    kinds = [_kind(m.group(2)) for m in found[:-1]]

    def digits(a: int, b: int) -> str:
        return "".join(m.group(1) for m in found[a : b + 1])

    whole = digits(0, len(found) - 1)
    if not kinds or (len(whole) <= 19 and _luhn(whole)):
        return [(0, len(run))]
    cards: list[tuple[int, int]] = []
    a = 0
    while a < len(kinds):
        kind = kinds[a]
        b = a
        while kind is not None and b < len(kinds) and kinds[b] == kind:
            b += 1
        number = digits(a, b)
        joined = kind is not None and len(kind) == 1
        if (
            b > a
            and len(number) >= 13
            and (joined or (len(number) <= 19 and _luhn(number)))
            and (not cards or spans[a][0] >= cards[-1][1])
        ):
            cards.append((spans[a][0], spans[b][1]))
        a = max(b, a + 1)
    return cards


def mask_card_runs(text: str, placeholder: str) -> tuple[str, int]:
    """Replace each card-like digit run with `placeholder`; return the text and the count."""
    out: list[str] = []
    count = 0
    last = 0
    for m in DIGIT_RUN.finditer(text):
        for start, end in _card_spans(m.group()):
            out += [text[last : m.start() + start], placeholder]
            last = m.start() + end
            count += 1
    out.append(text[last:])
    return "".join(out), count


def mask_digit_runs(text: str) -> str:
    return mask_card_runs(text, "[digits removed]")[0]


def log_event(event: str, **fields: str | float | bool | None) -> None:
    """Write one JSON line to stdout; any card-like run of 13+ digits is masked."""
    safe = {
        k: mask_digit_runs(v) if isinstance(v, str) else v for k, v in fields.items()
    }
    sys.stdout.write(json.dumps({"event": mask_digit_runs(event), **safe}) + "\n")
    sys.stdout.flush()
