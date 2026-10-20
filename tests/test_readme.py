"""S42: the README carries the eval numbers and the sections a reviewer checks."""

from tests.conftest import REPO

README = (REPO / "README.md").read_text()

SCENARIOS = [
    "AP-1",
    "AP-2",
    "AP-3",
    "BI-1",
    "BI-2",
    "BI-3",
    "BK-1",
    "BK-2",
    "BK-3",
    "DI-1",
    "LT-1",
    "ME-1",
    "ME-2",
    "ME-3",
    "NS-1",
    "RD-1",
    "RF-1",
    "SF-1",
    "SF-2",
    "SF-3",
    "T-1",
    "T-2",
    "T-3",
    "T-4",
    "T-5",
    "T-6",
    "T-7",
    "T-8",
    "WA-1",
    "WA-2",
    "WA-3",
]


def test_readme_lists_every_scenario_and_the_projection():
    for scenario_id in SCENARIOS:
        assert scenario_id in README
    assert "26.8%" in README
    assert "4 of 10" in README
    assert "12 of 12" in README
    assert "14 of 14" in README
    assert "no confidence interval" in README
    assert "120" in README and "45" in README and "42" in README
    assert "38" in README and "29" in README


def test_readme_has_the_run_clock_services_and_loop():
    assert "2026-10-16" in README and "2026-11-05" in README
    assert "OpenRouter" in README and "Railway" in README and "Langfuse" in README
    assert "Agrees with the labels on 20 of 20" in README
    assert "uv run python -m app" in README
    for step in ("logged", "flag", "draft", "export", "person", "evals.run"):
        assert step in README
    assert "docs/OPERATIONS.md" in README
