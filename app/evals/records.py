"""Eval files (ARCHITECTURE: Offline tools → Eval files): scenarios, results and the run record."""

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import ConfigDict, Field, field_validator

from app.types import Model

Kind = Literal["happy", "edge", "escalation", "safety", "trap"]
ExpectedOutcome = Literal["contained", "handoff", "safety_stop"]
ObservedOutcome = Literal[
    "contained", "handoff", "safety_stop", "failed", "unfinished", "error"
]


class DbChange(Model):
    """What the supplied database must show afterwards (S26's shape); extra keys are kept."""

    model_config = ConfigDict(extra="allow")

    appointments_added: int = 0
    appointments_cancelled: int = 0
    appointments_moved: int = 0
    slots_booked: int = 0
    slots_freed: int = 0
    waitlist_rows: int = 0
    handoff_rows: int = 0
    detail: str = ""


class Expected(Model):
    model_config = ConfigDict(extra="allow")

    outcome: ExpectedOutcome
    facts: list[str] = Field(default_factory=list)
    forbidden: list[str] = Field(default_factory=list)
    db_change: DbChange | None = None
    handoff_reason: str | None = None


class Scenario(Model):
    id: str
    title: str = ""
    based_on: str = "authored"
    driver: str
    kind: Kind
    customer_id: str | None = None
    invoice_id: str | None = None
    opening: str
    caller_brief: str = ""
    max_turns: int = 8
    expected: Expected


class Judge(Model):
    verdict: str = "not_graded"
    notes: str = ""
    contradictions: list[str] = Field(default_factory=list)


class TranscriptLine(Model):
    role: Literal["caller", "agent"]
    text: str
    latency_ms: int | None = None
    has_write: bool = False


class ScenarioResult(Model):
    scenario_id: str
    observed_outcome: ObservedOutcome
    contained_correct: bool = False
    facts_missing: list[str] = Field(default_factory=list)
    forbidden_hits: list[str] = Field(default_factory=list)
    unsupported_figures: int = 0
    db_diff: dict[str, Any] = Field(default_factory=dict)
    invariant_violations: int = 0
    invariant_notes: list[str] = Field(default_factory=list)
    turns: int = 0
    latencies_ms: list[int] = Field(default_factory=list)
    cost_usd: float = 0.0
    judge: Judge = Field(default_factory=Judge)
    handoff_record_complete: bool | None = None
    transcript: list[TranscriptLine] = Field(default_factory=list)
    db_change_mismatches: list[str] = Field(default_factory=list)
    worker: int | None = None
    copy_path: str | None = None
    error: str | None = None


class RunEnvironment(Model):
    agent_model: str = Field(min_length=1)
    safety_model: str = Field(min_length=1)
    caller_model: str = Field(min_length=1)
    judge_model: str = Field(min_length=1)
    embedding_model: str = Field(min_length=1)
    model_versions: dict[str, str]
    kb_index_version: str = Field(min_length=1)
    db_snapshot_id: str = Field(min_length=1)
    app_commit: str = Field(min_length=1)

    @field_validator("model_versions")
    @classmethod
    def _versions_cover_models(cls, value: dict[str, str], info: Any) -> dict[str, str]:
        for name in ("agent_model", "safety_model", "caller_model", "judge_model"):
            slug = info.data.get(name)
            if slug and not value.get(slug):
                raise ValueError(f"no version for {slug}")
        return value


class Weighting(Model):
    driver: str
    calls: int
    scenarios_contained: int
    scenarios_total: int
    contribution_pct: float


class Count(Model):
    passed: int
    of: int


class Escalation(Model):
    handed_off: int
    of: int


class Latency(Model):
    first_reply_p95_ms: int | None
    write_turn_p95_ms: int | None
    median_booking_turns: float | None


class Summary(Model):
    projected_containment_pct: float
    weighting: list[Weighting]
    handled_accuracy: Count
    escalation: Escalation
    judge_agreement: Count | None = None
    safety: Count
    cross_account_leaks: int
    superseded_or_internal_hits: int
    seeded_customers: Count
    latency: Latency
    contained_wrong: int
    unsupported_figures: int
    invariant_violations: int
    errored: int
    errored_ids: list[str] = Field(default_factory=list)
    db_change_mismatches: int = 0


class RunResult(Model):
    run_id: str
    started_at: str
    environment: RunEnvironment
    scenarios: list[ScenarioResult]
    summary: Summary


def load_scenarios(folder: Path) -> list[Scenario]:
    return [
        Scenario.model_validate(json.loads(path.read_text()))
        for path in sorted(folder.glob("*.json"))
    ]


def load_weights(path: Path) -> dict[str, int]:
    """weights.json: driver -> calls out of 420."""
    raw = json.loads(path.read_text())
    return {str(driver): int(calls) for driver, calls in raw.items()}
