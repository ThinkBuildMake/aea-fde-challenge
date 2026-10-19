import hashlib

import numpy as np

from app.context import AppContext
from app.errors import AppError
from app.knowledge.embeddings import EmbeddingUnavailable
from app.knowledge.index import LoadedIndex, build_lock, write_index
from app.knowledge.manifest import check_manifest, load_manifest
from app.knowledge.passages import PassageRecord, passages_for
from app.types import Fee, IndexStatus, Passage, RebuildIndexResult

__all__ = ["EmbeddingUnavailable"]


class IndexUnavailable(Exception):
    """No index is loaded."""


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
        matrix = np.asarray(vectors, dtype=np.float32)
        if matrix.ndim != 2 or matrix.shape[0] != len(passages):
            raise AppError(
                502,
                "embedding_failed",
                "The embedding provider returned unusable vectors.",
            )
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
