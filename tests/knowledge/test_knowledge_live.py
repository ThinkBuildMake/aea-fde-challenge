"""Opt-in checks with the real embeddings: MERIDIAN_LIVE_TESTS=1 and OPENROUTER_API_KEY."""

import os

import pytest
from pydantic import SecretStr

from app.context import AppContext
from app.knowledge.embeddings import OpenRouterEmbedder
from app.knowledge.service import get_fee, rebuild_index, search_knowledge
from app.main import create_app
from app.settings import Settings
from tests.knowledge.test_search import QUERIES, manifest_status

pytestmark = pytest.mark.skipif(
    os.environ.get("MERIDIAN_LIVE_TESTS") != "1"
    or not os.environ.get("OPENROUTER_API_KEY"),
    reason="live tests need MERIDIAN_LIVE_TESTS=1 and OPENROUTER_API_KEY",
)


@pytest.fixture
def live(kb_settings: Settings) -> tuple[AppContext, Settings]:
    settings = kb_settings.model_copy(
        update={"OPENROUTER_API_KEY": SecretStr(os.environ["OPENROUTER_API_KEY"])}
    )
    ctx = create_app(settings, embedder=OpenRouterEmbedder(settings)).state.ctx
    rebuild_index(ctx)
    return ctx, settings


def test_live_diagnostic_query_finds_89(live):
    ctx, _ = live
    results = search_knowledge(ctx, "Is the diagnostic fee $79?", 5)
    assert any("diagnostic" in r.text.lower() and "89" in r.text for r in results)


def test_live_no_retired_passage(live):
    ctx, settings = live
    status = manifest_status(settings)
    results = [p for q in QUERIES for p in search_knowledge(ctx, q, 5)]
    assert len(results) == 50
    assert {status[p.source_file] for p in results} == {"current"}


def test_live_fees(live):
    ctx, settings = live
    status = manifest_status(settings)
    assert get_fee(ctx, "FEE-DIAG").cents == 8900
    late = get_fee(ctx, "FEE-LATE")
    assert late.cents == 4900 and status[late.source_file] == "current"
