import hashlib
from decimal import Decimal, InvalidOperation

import numpy as np

from app.context import AppContext
from app.errors import AppError
from app.knowledge.embeddings import EmbeddingUnavailable
from app.knowledge.index import LoadedIndex, build_lock, write_index
from app.knowledge.manifest import check_manifest, load_manifest
from app.knowledge.passages import PassageRecord, passages_for
from app.types import Fee, IndexStatus, Passage, RebuildIndexResult

__all__ = ["EmbeddingUnavailable"]


FIRM_FEES = ("FEE-DIAG", "FEE-LATE", "FEE-AH", "FEE-HOL")


class IndexUnavailable(Exception):
    """No index is loaded."""


class UnknownFee(Exception):
    """The fee code is not in the price book."""


def search_knowledge(ctx: AppContext, query: str, k: int) -> list[Passage]:
    """The k nearest passages of the loaded index, best first; only current files are in it."""
    loaded = ctx.index.current()
    if loaded is None:
        raise IndexUnavailable("no index is loaded")
    if k <= 0:
        return []
    vector = np.asarray(ctx.embedder.embed([query])[0], dtype=np.float32)
    if vector.shape != (loaded.dims,):
        raise EmbeddingUnavailable("query vector has the wrong length")
    norms = np.linalg.norm(loaded.vectors, axis=1) * np.linalg.norm(vector)
    scores = loaded.vectors @ vector / np.where(norms == 0, 1.0, norms)
    best = np.argsort(-scores, kind="stable")[:k]
    return [
        Passage(
            passage_id=(p := loaded.passages[i]).passage_id,
            source_file=p.source_file,
            section=p.section,
            kind=p.kind,
            text=p.text,
            score=float(scores[i]),
        )
        for i in best
    ]


def get_fee(ctx: AppContext, code: str) -> Fee:
    """A firm fee read from the indexed current price book; ranges and unknown codes are refused."""
    if code not in FIRM_FEES:
        raise UnknownFee(code)
    loaded = ctx.index.current()
    if loaded is None:
        raise IndexUnavailable("no index is loaded")
    for p in loaded.passages:
        if p.kind != "price_row":
            continue
        row = dict(line.split(": ", 1) for line in p.text.splitlines() if ": " in line)
        if row.get("sku") != code:
            continue
        if row.get("low_price") != row.get("high_price"):
            break
        try:
            cents = int(Decimal(row["low_price"]) * 100)
        except (InvalidOperation, KeyError):
            break
        return Fee(code=code, cents=cents, source_file=p.source_file)
    raise UnknownFee(code)


def index_status(ctx: AppContext) -> IndexStatus:
    loaded = ctx.index.current()
    if loaded is None:
        return IndexStatus(loaded=False, version=None, passages=0)
    return IndexStatus(
        loaded=True, version=loaded.version, passages=len(loaded.passages)
    )


def rebuild_index(ctx: AppContext) -> RebuildIndexResult:
    """Build the index from the manifest's current files; on any failure the old index stays in force."""
    kb_dir = ctx.settings.KB_DIR
    with build_lock(ctx.settings.INDEX_PATH):
        manifest = load_manifest(kb_dir)
        check_manifest(kb_dir, manifest)
        passages: list[PassageRecord] = []
        for rel, entry in manifest.items():
            if entry.status == "current":
                passages.extend(passages_for(kb_dir, rel, entry))
        if not passages:
            raise AppError(
                422, "manifest_invalid", "The manifest lists no current file."
            )
        try:
            vectors = ctx.embedder.embed([p.text for p in passages])
        except EmbeddingUnavailable:
            raise AppError(
                502,
                "embedding_failed",
                "The embedding provider failed; the old index stays in use.",
            ) from None
        unusable = AppError(
            502,
            "embedding_failed",
            "The embedding provider returned unusable vectors.",
        )
        try:
            matrix = np.asarray(vectors, dtype=np.float32)
        except (ValueError, TypeError):
            raise unusable from None
        if matrix.ndim != 2 or matrix.shape[0] != len(passages):
            raise unusable
        digest = hashlib.sha256(ctx.embedder.model.encode())
        for p in passages:
            digest.update(f"\0{p.passage_id}\0{p.text}".encode())
        loaded = LoadedIndex(
            version="idx-" + digest.hexdigest()[:12],
            model=ctx.embedder.model,
            dims=int(matrix.shape[1]),
            passages=passages,
            vectors=matrix,
        )
        write_index(ctx.settings.INDEX_PATH, loaded)
        ctx.index.swap(loaded)
        return RebuildIndexResult(
            index_version=loaded.version,
            passages=len(passages),
            sources=len({p.source_file for p in passages}),
        )
