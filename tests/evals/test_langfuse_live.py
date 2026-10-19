"""Opt-in: reports a real run to the Langfuse project named by LANGFUSE_* and reads it back."""

import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx2
import pytest
from pydantic import SecretStr

from app.evals.langfuse_report import langfuse_reporter
from app.settings import Settings
from tests.evals.helpers import eight_scenarios, play

pytestmark = pytest.mark.skipif(
    os.environ.get("MERIDIAN_LIVE_TESTS") != "1"
    or not os.environ.get("LANGFUSE_PUBLIC_KEY")
    or not os.environ.get("LANGFUSE_SECRET_KEY"),
    reason="live test: needs MERIDIAN_LIVE_TESTS=1 and LANGFUSE_* keys",
)


def test_run_is_an_experiment(live: Settings, tmp_path: Path):
    settings = live.model_copy(
        update={
            "LANGFUSE_PUBLIC_KEY": SecretStr(os.environ["LANGFUSE_PUBLIC_KEY"]),
            "LANGFUSE_SECRET_KEY": SecretStr(os.environ["LANGFUSE_SECRET_KEY"]),
            "LANGFUSE_BASE_URL": os.environ.get(
                "LANGFUSE_BASE_URL", live.LANGFUSE_BASE_URL
            ),
        }
    )
    reporter = langfuse_reporter(settings)
    assert reporter is not None
    run = play(live, tmp_path, eight_scenarios()[:2], reporter=reporter)
    auth = (os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"])
    base = settings.LANGFUSE_BASE_URL.rstrip("/")
    since = (datetime.now(UTC) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    items: list[dict] = []
    experiments: list[dict] = []
    for _ in range(24):
        found = httpx2.get(
            f"{base}/api/public/experiments",
            params={"name": run.run_id, "fromStartTime": since},
            auth=auth,
            timeout=20,
        )
        experiments = found.json().get("data", []) if found.status_code == 200 else []
        if experiments:
            got = httpx2.get(
                f"{base}/api/public/experiment-items",
                params={
                    "experimentName": run.run_id,
                    "fields": "core,io",
                    "fromStartTime": since,
                },
                auth=auth,
                timeout=20,
            )
            items = got.json().get("data", []) if got.status_code == 200 else []
            if len(items) >= 2:
                break
        time.sleep(5)
    print(
        f"experiment name={experiments[0]['name'] if experiments else None} run id={run.run_id} items={len(items)}"
    )
    assert len(experiments) == 1 and len(items) == 2
    outputs = [
        json.loads(i["output"]) if isinstance(i["output"], str) else i["output"]
        for i in items
    ]
    seen = sorted(o["observedOutcome"] for o in outputs)
    print("observed outcomes in Langfuse:", seen)
    assert seen == sorted(r.observed_outcome for r in run.scenarios)
