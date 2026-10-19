import json

from tests.conftest import REPO


def test_weights_match_the_audit():
    weights = json.loads((REPO / "eval" / "weights.json").read_text())
    assert weights == {
        "booking": 120,
        "warranty": 45,
        "billing": 42,
        "membership": 38,
        "appointment": 29,
    }
    assert sum(weights.values()) == 274
