"""Report a finished run to Langfuse as one experiment, one item per scenario.

Fire-and-forget: the run record file is the source of truth, so every failure here is logged
as one line and swallowed. Only ids, expected outcome and counts are sent, never the caller's
words, transcripts or conversation ids (CP-1).
"""

import json
import logging
from typing import Any

from app.evals.records import RunResult, Scenario, ScenarioResult
from app.evals.runner import Reporter
from app.settings import Settings

log = logging.getLogger("meridian.evals")

REQUEST_TIMEOUT_S = 5


def _output(result: ScenarioResult) -> dict[str, Any]:
    return {
        "observedOutcome": result.observed_outcome,
        "containedCorrect": result.contained_correct,
        "unsupportedFigures": result.unsupported_figures,
        "invariantViolations": result.invariant_violations,
        "turns": result.turns,
        "costUsd": result.cost_usd,
        "error": result.error,
    }


def report_to_langfuse(
    run: RunResult,
    scenarios: list[Scenario],
    *,
    public_key: str,
    secret_key: str,
    base_url: str,
    timeout_s: int = REQUEST_TIMEOUT_S,
) -> None:
    try:
        from langfuse import Evaluation, Langfuse

        by_id = {r.scenario_id: r for r in run.scenarios}
        client = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            base_url=base_url,
            timeout=timeout_s,
        )

        def task(*, item: Any, **_: Any) -> dict[str, Any]:
            return _output(by_id[item["input"]["scenarioId"]])

        def observed_outcome(*, output: Any, **_: Any) -> Any:
            return Evaluation(
                name="observed_outcome",
                value=output["observedOutcome"],
                data_type="CATEGORICAL",
            )

        def contained_correct(*, output: Any, **_: Any) -> Any:
            return Evaluation(
                name="contained_correct", value=1 if output["containedCorrect"] else 0
            )

        data: Any = [
            {
                "input": {"scenarioId": s.id, "driver": s.driver, "kind": s.kind},
                "expected_output": s.expected.outcome,
                "metadata": {"scenarioId": s.id},
            }
            for s in scenarios
        ]
        client.run_experiment(
            name=run.run_id,
            run_name=run.run_id,
            description=f"Meridian eval run {run.run_id}",
            data=data,
            task=task,
            evaluators=[observed_outcome, contained_correct],
            max_concurrency=4,
            metadata={
                "appCommit": run.environment.app_commit,
                "kbIndexVersion": run.environment.kb_index_version,
                "dbSnapshotId": run.environment.db_snapshot_id,
            },
        )
        client.flush()
    except Exception as error:  # noqa: BLE001 - reporting never fails the run
        log.warning(
            json.dumps(
                {"event": "langfuse_report_failed", "error_type": type(error).__name__}
            )
        )


def langfuse_reporter(settings: Settings) -> Reporter | None:
    """The reporter for these settings, or None when the Langfuse keys are not set."""
    if settings.LANGFUSE_PUBLIC_KEY is None or settings.LANGFUSE_SECRET_KEY is None:
        return None
    public_key = settings.LANGFUSE_PUBLIC_KEY.get_secret_value()
    secret_key = settings.LANGFUSE_SECRET_KEY.get_secret_value()

    def report(run: RunResult, scenarios: list[Scenario]) -> None:
        report_to_langfuse(
            run,
            scenarios,
            public_key=public_key,
            secret_key=secret_key,
            base_url=settings.LANGFUSE_BASE_URL,
        )

    return report
