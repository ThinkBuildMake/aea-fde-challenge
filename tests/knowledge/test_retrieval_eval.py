"""The retrieval eval command (EV-4, VR-3), offline with fake or stub embeddings."""

import json
from pathlib import Path

import numpy as np
import pytest

from app.knowledge import retrieval_eval
from app.knowledge.embeddings import EmbeddingUnavailable, FakeEmbedder
from app.knowledge.index import LoadedIndex, write_index
from app.knowledge.passages import PassageRecord
from app.knowledge.retrieval_eval import (
    RetrievalQuestion,
    load_questions,
    run_retrieval_eval,
)
from app.knowledge.service import rebuild_index
from app.settings import Settings
from tests.conftest import REPO
from tests.knowledge.test_rebuild import make_ctx

QUESTIONS = REPO / "eval" / "retrieval" / "questions.json"


@pytest.fixture
def env(kb_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Settings:
    for name, value in {
        "OPENROUTER_API_KEY": "test-key",
        "ADMIN_TOKEN": "test-admin-token",
        "SCHEDULING_DB_PATH": kb_settings.SCHEDULING_DB_PATH,
        "APP_DB_PATH": kb_settings.APP_DB_PATH,
        "INDEX_PATH": kb_settings.INDEX_PATH,
        "KB_DIR": kb_settings.KB_DIR,
    }.items():
        monkeypatch.setenv(name, str(value))
    kb_settings.INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    return kb_settings


class StubEmbedder:
    """Returns a chosen vector per query; raises for an unknown query."""

    model = "stub-embedding"

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self.vectors = vectors

    def embed(self, texts: list[str]) -> list[list[float]]:
        if texts[0] not in self.vectors:
            raise EmbeddingUnavailable("stub failure")
        return [self.vectors[t] for t in texts]


def hand_built(settings: Settings, sources: list[str]) -> None:
    """One passage per source, passage i pointing along axis i."""
    passages = [
        PassageRecord(f"p{i}", source, "", "text", f"text {i}")
        for i, source in enumerate(sources)
    ]
    settings.INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_index(
        settings.INDEX_PATH,
        LoadedIndex(
            "idx-hand",
            StubEmbedder.model,
            len(sources),
            passages,
            np.eye(len(sources), dtype=np.float32),
        ),
    )


def question(qid: str, text: str, expected: str) -> RetrievalQuestion:
    return RetrievalQuestion(
        id=qid,
        driver="billing",
        question=text,
        expected_sources=[expected],
        must_not_return=["archive/warranty_terms_2023.txt"],
    )


def test_command_writes_report_for_every_question(env: Settings, tmp_path: Path):
    rebuild_index(make_ctx(env))
    out = tmp_path / "out" / "report.json"
    assert (
        retrieval_eval.main(["--k", "5", "--out", str(out)], embedder=FakeEmbedder())
        == 0
    )
    report = json.loads(out.read_text())
    ids = [q["id"] for q in json.loads(QUESTIONS.read_text())]
    assert set(report) == {"hitsInTop5", "of", "supersededInTop5", "perQuestion"}
    assert report["of"] == len(ids)
    assert [r["id"] for r in report["perQuestion"]] == ids
    for row in report["perQuestion"]:
        assert set(row) == {"id", "hit", "topSources"}
        assert isinstance(row["hit"], bool)
        assert len(row["topSources"]) == 5
    print(
        f"of={report['of']} hitsInTop5={report['hitsInTop5']} "
        f"supersededInTop5={report['supersededInTop5']}"
    )
    for row in report["perQuestion"]:
        print(row["id"], "hit" if row["hit"] else "miss", row["topSources"])


def test_hit_and_miss_on_hand_built_index(kb_settings: Settings):
    sources = [
        "faq/customer_faq.md",
        "warranty/warranty_policy.md",
        "policies/service_area.md",
    ]
    hand_built(kb_settings, sources)
    ctx = make_ctx(kb_settings, StubEmbedder({"near": [1, 0, 0], "far": [0.9, 0.1, 0]}))  # type: ignore[arg-type]
    report = run_retrieval_eval(
        ctx,
        [
            question("Q1", "near", "faq/customer_faq.md"),
            question("Q2", "far", "policies/service_area.md"),
            question("Q3", "broken", "faq/customer_faq.md"),
        ],
        k=2,
    )
    rows = {r.id: r for r in report.per_question}
    assert rows["Q1"].hit is True
    assert rows["Q1"].top_sources == [
        "faq/customer_faq.md",
        "warranty/warranty_policy.md",
    ]
    assert rows["Q2"].hit is False
    assert rows["Q3"].hit is False and rows["Q3"].top_sources == []
    assert report.hits_in_top5 == 1 and report.of == 3
    assert report.superseded_in_top5 == 0
    print(report.model_dump_json(by_alias=True))


def test_superseded_passage_is_counted(kb_settings: Settings):
    sources = ["faq/faq_old_copy.md", "faq/customer_faq.md", "policies/service_area.md"]
    hand_built(kb_settings, sources)
    ctx = make_ctx(kb_settings, StubEmbedder({"old": [1, 0.5, 0], "area": [0, 0, 1]}))  # type: ignore[arg-type]
    report = run_retrieval_eval(
        ctx,
        [
            question("Q1", "old", "faq/customer_faq.md"),
            question("Q2", "area", "policies/service_area.md"),
        ],
        k=1,
    )
    assert report.superseded_in_top5 == 1
    assert [r.top_sources for r in report.per_question] == [
        ["faq/faq_old_copy.md"],
        ["policies/service_area.md"],
    ]
    print(f"supersededInTop5={report.superseded_in_top5}")


def test_missing_index_stops_without_report(env: Settings, tmp_path: Path, capsys):
    out = tmp_path / "report.json"
    embedder = FakeEmbedder()
    assert retrieval_eval.main(["--k", "5", "--out", str(out)], embedder=embedder) == 1
    err = capsys.readouterr().err.strip()
    error = json.loads(err)
    assert error["error"] == "index_unavailable"
    assert "index" in error["message"]
    assert not out.exists()
    assert embedder.calls == 0
    print(f"exit=1 stderr={err} report_exists={out.exists()}")


def test_bad_question_file_stops_without_report(env: Settings, tmp_path: Path, capsys):
    rebuild_index(make_ctx(env))
    bad = tmp_path / "bad.json"
    bad.write_text('[{"id": "x"}]')
    out = tmp_path / "report.json"
    assert (
        retrieval_eval.main(
            ["--questions", str(bad), "--out", str(out)], embedder=FakeEmbedder()
        )
        == 1
    )
    assert json.loads(capsys.readouterr().err)["error"] == "questions_invalid"
    assert not out.exists()


def test_gate_runs_same_questions_with_fake_embeddings(kb_settings: Settings):
    ctx = make_ctx(kb_settings)
    rebuild_index(ctx)
    questions = load_questions(QUESTIONS)
    report = run_retrieval_eval(ctx, questions, 5)
    assert report.of == len(questions) >= 20
    assert all(len(r.top_sources) == 5 for r in report.per_question)
    assert report.superseded_in_top5 == 0
