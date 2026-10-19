import json
import time
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from app.evals.langfuse_report import langfuse_reporter, report_to_langfuse
from app.evals.run import format_summary
from app.settings import Settings
from tests.evals.helpers import eight_scenarios, play


def keyed(settings: Settings, base_url: str) -> Settings:
    return settings.model_copy(
        update={
            "LANGFUSE_PUBLIC_KEY": SecretStr("pk-test"),
            "LANGFUSE_SECRET_KEY": SecretStr("sk-test"),
            "LANGFUSE_BASE_URL": base_url,
        }
    )


def test_unreachable_langfuse_still_writes_the_record(live: Settings, tmp_path: Path):
    settings = keyed(live, "http://127.0.0.1:9")
    reporter = langfuse_reporter(settings)
    assert reporter is not None
    started = time.monotonic()
    run = play(
        live, tmp_path, eight_scenarios()[:2], reporter=reporter, reporter_timeout_s=10
    )
    took = time.monotonic() - started
    record = json.loads((tmp_path / "runs" / "run.json").read_text())
    print(f"finished in {took:.1f}s, record holds {len(record['scenarios'])} scenarios")
    assert took < 30
    assert record["runId"] == run.run_id and len(record["scenarios"]) == 2


def test_items_carry_observed_outcome(
    live: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    calls: list[dict[str, Any]] = []
    outputs: list[Any] = []

    class Recorder:
        def __init__(self, **kwargs: Any) -> None:
            calls.append({"init": kwargs})

        def run_experiment(self, **kwargs: Any) -> None:
            calls.append(kwargs)
            for item in kwargs["data"]:
                outputs.append(kwargs["task"](item=item))

        def flush(self) -> None:
            pass

    monkeypatch.setattr("langfuse.Langfuse", Recorder)
    run = play(live, tmp_path, eight_scenarios()[:2])
    report_to_langfuse(
        run,
        eight_scenarios()[:2],
        public_key="pk",
        secret_key="sk",
        base_url="http://example.invalid",
    )
    (experiment,) = [c for c in calls if "name" in c]
    print(experiment["name"], outputs)
    assert experiment["name"] == run.run_id and len(experiment["data"]) == 2
    assert [o["observedOutcome"] for o in outputs] == [
        r.observed_outcome for r in run.scenarios
    ]
    sent = json.dumps([experiment["data"], outputs, experiment["metadata"]])
    for secret in ("Linda", "512-555", "transcript", "conversationId"):
        assert secret not in sent


def test_no_keys_means_no_reporter(live: Settings):
    bare = live.model_copy(
        update={"LANGFUSE_PUBLIC_KEY": None, "LANGFUSE_SECRET_KEY": None}
    )
    assert langfuse_reporter(bare) is None
    assert langfuse_reporter(keyed(live, "http://x")) is not None


def test_format_summary_prints_the_ev3_numbers(live: Settings, tmp_path: Path):
    run = play(live, tmp_path, eight_scenarios()[:2])
    text = format_summary(run)
    print(text)
    for label in (
        "Projected containment",
        "Handled accuracy",
        "Escalation handed off",
        "Safety",
        "Cross-account leaks",
        "Superseded or internal hits",
        "Seeded customers booked",
        "Latency",
        "Errored: 0",
    ):
        assert label in text


def test_only_the_error_type_goes_to_langfuse():
    from app.evals.langfuse_report import _output
    from app.evals.records import ScenarioResult

    out = _output(
        ScenarioResult(
            scenario_id="X",
            observed_outcome="error",
            error="RuntimeError: provider said secret-ish text",
        )
    )
    assert out["error"] == "RuntimeError"
