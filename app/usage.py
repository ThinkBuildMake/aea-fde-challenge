"""A per-call usage channel: providers report tokens and cost, the caller that opened `collect` reads them."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None


_open: ContextVar[list[Usage] | None] = ContextVar("usage", default=None)


def report(usage: Usage) -> None:
    """Record one provider call's usage for whoever is collecting in this context; else a no-op."""
    seen = _open.get()
    if seen is not None:
        seen.append(usage)


def _add[N: (int, float)](values: list[N | None]) -> N | None:
    known = [v for v in values if v is not None]
    return sum(known[1:], known[0]) if known else None


def total(seen: list[Usage]) -> Usage:
    """Sum the reported calls; a field nobody reported stays None."""
    return Usage(
        input_tokens=_add([u.input_tokens for u in seen]),
        output_tokens=_add([u.output_tokens for u in seen]),
        cost_usd=_add([u.cost_usd for u in seen]),
    )


@contextmanager
def collect() -> Iterator[list[Usage]]:
    """Collect the usage reported inside the block, in this thread or task."""
    seen: list[Usage] = []
    token = _open.set(seen)
    try:
        yield seen
    finally:
        _open.reset(token)
