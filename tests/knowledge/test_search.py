import json

import pytest

from app.context import AppContext
from app.knowledge.embeddings import EmbeddingUnavailable, FakeEmbedder
from app.knowledge.service import (
    IndexUnavailable,
    index_status,
    rebuild_index,
    search_knowledge,
)
from app.settings import Settings
from app.types import IndexStatus
from tests.knowledge.test_rebuild import make_ctx

QUERIES = [
    "How much notice do I need to give to cancel?",
    "What is the cancellation notice period?",
    "Cancellation notice hours before the visit",
    "How long is the warranty?",
    "What is the warranty length on repairs?",
    "Warranty period for parts and labor",
    "How much does a membership cost?",
    "Membership price per year",
    "When are fees waived?",
    "Is the diagnostic fee waived for members?",
]
RETIRED_VALUES = ["$79", "48 hour", "48-hour", "90-day", "$149 per year"]


def built(settings: Settings, embedder: FakeEmbedder | None = None) -> AppContext:
    ctx = make_ctx(settings, embedder)
    rebuild_index(ctx)
    return ctx


def manifest_status(settings: Settings) -> dict[str, str]:
    files = json.loads((settings.KB_DIR.parent / "kb_manifest.json").read_text())[
        "files"
    ]
    return {name: entry["status"] for name, entry in files.items()}


def test_nearest_current_passage_first(kb_settings: Settings):
    ctx = built(kb_settings)
    results = search_knowledge(ctx, "Is the diagnostic fee $79?", 5)
    assert len(results) <= 5
    assert [r.score for r in results] == sorted(
        (r.score for r in results), reverse=True
    )
    assert any("diagnostic" in r.text.lower() and "89" in r.text for r in results)


def test_no_retired_passage_in_50_results(kb_settings: Settings):
    ctx = built(kb_settings)
    status = manifest_status(kb_settings)
    results = [p for q in QUERIES for p in search_knowledge(ctx, q, 5)]
    assert len(results) == 50
    assert {status[p.source_file] for p in results} == {"current"}


def test_no_superseded_values_returned(kb_settings: Settings):
    ctx = built(kb_settings)
    queries = QUERIES + [
        "$79 diagnostic",
        "48 hours notice",
        "90-day warranty",
        "$149 per year membership",
    ]
    for q in queries:
        for p in search_knowledge(ctx, q, 5):
            assert not any(v in p.text for v in RETIRED_VALUES), (q, p.passage_id)
            assert not p.source_file.startswith(("archive/", "internal/"))


def test_missing_index_reported(kb_settings: Settings):
    embedder = FakeEmbedder()
    ctx = make_ctx(kb_settings, embedder)
    with pytest.raises(IndexUnavailable):
        search_knowledge(ctx, "anything", 5)
    assert embedder.calls == 0
    assert index_status(ctx) == IndexStatus(loaded=False, version=None, passages=0)
    result = rebuild_index(ctx)
    assert index_status(ctx) == IndexStatus(
        loaded=True, version=result.index_version, passages=result.passages
    )


def test_failed_embedding_reported(kb_settings: Settings):
    embedder = FakeEmbedder()
    ctx = built(kb_settings, embedder)
    embedder.fail = True
    with pytest.raises(EmbeddingUnavailable):
        search_knowledge(ctx, "anything", 5)


def test_query_vector_of_wrong_length_reported(kb_settings: Settings):
    ctx = built(kb_settings)
    ctx.embedder = FakeEmbedder(dims=8)
    with pytest.raises(EmbeddingUnavailable):
        search_knowledge(ctx, "anything", 5)


def test_k_bounds(kb_settings: Settings):
    ctx = built(kb_settings)
    assert search_knowledge(ctx, "diagnostic", 0) == []
    total = index_status(ctx).passages
    assert len(search_knowledge(ctx, "diagnostic", total + 10)) == total
