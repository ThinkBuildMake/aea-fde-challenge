"""Opt-in retrieval eval with the real embeddings (EV-4): MERIDIAN_LIVE_TESTS=1 and OPENROUTER_API_KEY."""

import gc
import math
import os

import pytest
from pydantic import SecretStr

from app.knowledge.embeddings import OpenRouterEmbedder
from app.knowledge.retrieval_eval import load_questions, run_retrieval_eval
from app.knowledge.service import rebuild_index
from app.main import create_app
from app.settings import Settings
from tests.conftest import REPO

pytestmark = pytest.mark.skipif(
    os.environ.get("MERIDIAN_LIVE_TESTS") != "1"
    or not os.environ.get("OPENROUTER_API_KEY"),
    reason="live tests need MERIDIAN_LIVE_TESTS=1 and OPENROUTER_API_KEY",
)


# The embedder's per-call OpenAI client leaves its socket to the garbage collector.
@pytest.mark.filterwarnings("ignore::ResourceWarning")
@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
def test_live_hits_and_superseded(kb_settings: Settings):
    settings = kb_settings.model_copy(
        update={"OPENROUTER_API_KEY": SecretStr(os.environ["OPENROUTER_API_KEY"])}
    )
    ctx = create_app(settings, embedder=OpenRouterEmbedder(settings)).state.ctx
    built = rebuild_index(ctx)
    questions = load_questions(REPO / "eval" / "retrieval" / "questions.json")
    report = run_retrieval_eval(ctx, questions, 5)
    gc.collect()
    print(
        f"index={built.index_version} passages={built.passages} sources={built.sources}"
    )
    print(
        f"of={report.of} hitsInTop5={report.hits_in_top5} "
        f"supersededInTop5={report.superseded_in_top5}"
    )
    for row in report.per_question:
        print(row.id, "hit" if row.hit else "MISS", row.top_sources)
    misses = [(r.id, r.top_sources) for r in report.per_question if not r.hit]
    assert report.of >= 20
    assert report.hits_in_top5 >= max(18, math.ceil(0.9 * report.of)), misses
    assert report.superseded_in_top5 <= 1
