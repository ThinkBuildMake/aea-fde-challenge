"""S42 (EV-6): a read of 20 random calls agrees with the rule labels on >= 17."""

import csv
import random

from tests.conftest import REPO

LABELS = REPO / "analysis" / "call_labels.csv"
SAMPLE = REPO / "analysis" / "label_sample.csv"
TRANSCRIPTS = REPO / "data" / "meridian_dataset" / "call_transcripts"
AUDIT = REPO / "docs" / "AUDIT.md"
SEED = 20261019


def _rows(path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def test_sample_is_twenty_real_calls_with_their_labels():
    labels = {r["call_id"]: r["intent"] for r in _rows(LABELS)}
    sample = _rows(SAMPLE)
    ids = [r["call_id"] for r in sample]
    print("sample size", len(ids), "distinct", len(set(ids)), "seed", SEED)
    assert ids == random.Random(SEED).sample(sorted(labels), 20)
    for row in sample:
        assert row["intent"] == labels[row["call_id"]]
        assert row["reader_intent"]
        assert row["agree"] in ("yes", "no")
        assert row["agree"] == (
            "yes" if row["reader_intent"] == row["intent"] else "no"
        )
        assert (TRANSCRIPTS / f"{row['call_id']}.txt").is_file()


def test_agreement_line_matches_the_sample():
    agree = sum(r["agree"] == "yes" for r in _rows(SAMPLE))
    line = f"Agrees with the labels on {agree} of 20"
    print(line)
    assert agree >= 17
    assert line in AUDIT.read_text()
