"""The runRetrievalEval command: python -m app.knowledge.retrieval_eval [--questions PATH] [--k N] [--out PATH]

Runs each retrieval question through the real search and writes a RetrievalReport (EV-4).
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Literal

from pydantic import TypeAdapter, ValidationError

from app.context import AppContext
from app.knowledge.embeddings import Embedder, EmbeddingUnavailable
from app.knowledge.manifest import load_manifest
from app.knowledge.service import IndexUnavailable, search_knowledge
from app.main import create_app
from app.settings import load_settings_or_exit
from app.types import Model

REPO = Path(__file__).resolve().parent.parent.parent
DEFAULT_QUESTIONS = REPO / "eval" / "retrieval" / "questions.json"
DEFAULT_OUT = REPO / "eval" / "results" / "retrieval_report.json"


class RetrievalQuestion(Model):
    id: str
    driver: Literal["booking", "warranty", "billing"]
    question: str
    expected_sources: list[str]
    must_not_return: list[str]


class QuestionResult(Model):
    id: str
    hit: bool
    top_sources: list[str]


class RetrievalReport(Model):
    hits_in_top5: int
    of: int
    superseded_in_top5: int
    per_question: list[QuestionResult]


def load_questions(path: Path) -> list[RetrievalQuestion]:
    return TypeAdapter(list[RetrievalQuestion]).validate_json(path.read_bytes())


def run_retrieval_eval(
    ctx: AppContext, questions: list[RetrievalQuestion], k: int = 5
) -> RetrievalReport:
    """A question whose search fails is a miss; a missing index raises IndexUnavailable."""
    if ctx.index.current() is None:
        raise IndexUnavailable("no index is loaded")
    status = {rel: e.status for rel, e in load_manifest(ctx.settings.KB_DIR).items()}
    rows: list[QuestionResult] = []
    superseded = 0
    for q in questions:
        try:
            top = [p.source_file for p in search_knowledge(ctx, q.question, k)]
        except EmbeddingUnavailable:
            top = []
        if any(s in q.must_not_return or status.get(s) != "current" for s in top):
            superseded += 1
        hit = any(s in q.expected_sources for s in top)
        rows.append(QuestionResult(id=q.id, hit=hit, top_sources=top))
    return RetrievalReport(
        hits_in_top5=sum(r.hit for r in rows),
        of=len(rows),
        superseded_in_top5=superseded,
        per_question=rows,
    )


def _fail(code: str, message: str) -> int:
    sys.stderr.write(json.dumps({"error": code, "message": message}) + "\n")
    return 1


def main(argv: list[str] | None = None, *, embedder: Embedder | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.knowledge.retrieval_eval")
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    if args.k < 1:
        parser.error("--k must be at least 1")
    try:
        questions = load_questions(args.questions)
    except (OSError, ValidationError):
        return _fail(
            "questions_invalid", f"The question file {args.questions} cannot be read."
        )
    settings = load_settings_or_exit()
    ctx = create_app(settings, embedder=embedder).state.ctx
    try:
        report = run_retrieval_eval(ctx, questions, args.k)
    except IndexUnavailable:
        return _fail(
            "index_unavailable",
            "No index is loaded; run python -m app.knowledge.rebuild first.",
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report.model_dump_json(by_alias=True, indent=2) + "\n")
    summary = {
        "hitsInTop5": report.hits_in_top5,
        "of": report.of,
        "supersededInTop5": report.superseded_in_top5,
        "report": str(args.out),
    }
    sys.stdout.write(json.dumps(summary) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
