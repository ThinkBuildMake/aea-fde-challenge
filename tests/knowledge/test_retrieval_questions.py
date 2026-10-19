"""File check over the retrieval questions (EV-4)."""

import json
from collections import Counter

from tests.conftest import REPO

QUESTIONS = REPO / "eval" / "retrieval" / "questions.json"
MANIFEST = REPO / "data" / "meridian_dataset" / "kb_manifest.json"
KEYS = {"id", "driver", "question", "expectedSources", "mustNotReturn"}


def test_question_file_is_complete():
    questions = json.loads(QUESTIONS.read_text())
    status = {
        rel: entry["status"]
        for rel, entry in json.loads(MANIFEST.read_text())["files"].items()
    }
    assert isinstance(questions, list) and len(questions) >= 20
    assert len({q["id"] for q in questions}) == len(questions)
    drivers = Counter(q["driver"] for q in questions)
    assert set(drivers) == {"booking", "warranty", "billing"}
    assert min(drivers.values()) >= 5
    for q in questions:
        assert set(q) == KEYS, q["id"]
        assert q["question"].strip(), q["id"]
        assert q["expectedSources"], q["id"]
        assert all(status.get(s) == "current" for s in q["expectedSources"]), q["id"]
        assert q["mustNotReturn"], q["id"]
        assert all(
            s in status and status[s] != "current" for s in q["mustNotReturn"]
        ), q["id"]
    print(f"questions={len(questions)} drivers={dict(sorted(drivers.items()))}")
