from app.context import AppContext
from app.types import Fee, IndexStatus, Passage, RebuildIndexResult


class IndexUnavailable(Exception):
    """No index is loaded."""


class EmbeddingUnavailable(Exception):
    """The embedding provider failed."""


class UnknownFee(Exception):
    """The fee code is not in the price book."""


def search_knowledge(ctx: AppContext, query: str, k: int) -> list[Passage]:
    """Stub: no passages."""
    return []


def get_fee(ctx: AppContext, code: str) -> Fee:
    """Stub: no fee is known."""
    raise UnknownFee(code)


def index_status(ctx: AppContext) -> IndexStatus:
    return IndexStatus(loaded=False, version=None, passages=0)


def rebuild_index(ctx: AppContext) -> RebuildIndexResult:
    """Stub: builds nothing."""
    return RebuildIndexResult(index_version="stub", passages=0, sources=0)
