"""The judge on two fixed transcripts with the real JUDGE_MODEL (opt-in: MERIDIAN_LIVE_TESTS=1)."""

import os

import pytest
from pydantic import SecretStr

from app.evals.judge import Grade, OpenRouterJudge, grade_answer
from app.evals.records import FactCheck
from app.settings import Settings
from tests.evals.test_judge import FACT, scenario, transcript

pytestmark = pytest.mark.skipif(
    os.environ.get("MERIDIAN_LIVE_TESTS") != "1"
    or not os.environ.get("OPENROUTER_API_KEY"),
    reason="real judge model; opt-in",
)


def _grade(tmp_settings: Settings, agent_line: str) -> Grade:
    settings = tmp_settings.model_copy(
        update={"OPENROUTER_API_KEY": SecretStr(os.environ["OPENROUTER_API_KEY"])}
    )
    judge = OpenRouterJudge(settings)
    try:
        grade = grade_answer(scenario(FACT), transcript(agent_line), judge)
    finally:
        judge.close()
    print(
        f"\njudge model: {settings.JUDGE_MODEL}\nagent line: {agent_line}\n"
        f"verdict: {grade.judge.verdict}\n"
        f"facts: {[c.model_dump() for c in grade.judge.facts]}\n"
        f"facts missing: {grade.facts_missing}\n"
        f"contradictions: {grade.judge.contradictions}\ncost usd: {grade.cost_usd}"
    )
    return grade


def test_present_fact_is_found(tmp_settings: Settings) -> None:
    grade = _grade(
        tmp_settings,
        "The diagnostic fee is $89, and it is waived if you go ahead with the repair.",
    )
    assert grade.judge.facts == [FactCheck(fact=FACT, present=True)]
    assert grade.facts_missing == []
    assert grade.judge.contradictions == []
    assert grade.judge.verdict == "pass"


def test_contradiction_is_found(tmp_settings: Settings) -> None:
    grade = _grade(tmp_settings, "Our diagnostic fee is $79.")
    assert grade.judge.facts == [FactCheck(fact=FACT, present=False)]
    assert grade.facts_missing == [FACT]
    assert len(grade.judge.contradictions) >= 1
    assert grade.judge.verdict == "fail"
