"""python -m app.evals.langfuse_check RUN.json — read the run's Langfuse experiment back.

Finds the experiment named by the run id and checks it holds one item per scenario with the
record's observed outcome. Reads /api/public/experiments and /api/public/experiment-items
(the v1 traces list is gone). Needs LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY in the
environment; prints counts and outcomes only, never a key.
"""

import argparse
import json
import os
import sys
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.evals.compare import read_run
from app.evals.records import RunResult

Fetch = Callable[[str, dict[str, Any]], dict[str, Any]]
DEFAULT_BASE_URL = "https://us.cloud.langfuse.com"


def _json(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def check(run: RunResult, fetch: Fetch) -> tuple[bool, str]:
    """(every scenario is in the one experiment with the record's outcome, the report)."""
    started = datetime.fromisoformat(run.started_at)
    since = (started - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    experiments = [
        e
        for e in fetch(
            "/api/public/experiments", {"name": run.run_id, "fromStartTime": since}
        ).get("data", [])
        if e.get("name") == run.run_id
    ]
    items = fetch(
        "/api/public/experiment-items",
        {
            "experimentName": run.run_id,
            "fields": "core,io",
            "fromStartTime": since,
            "limit": 100,
        },
    ).get("data", [])
    seen: dict[str, str | None] = {}
    for item in items:
        sid = _json(item.get("input")).get("scenarioId")
        if sid:
            seen[str(sid)] = _json(item.get("output")).get("observedOutcome")
    expected = {r.scenario_id: r.observed_outcome for r in run.scenarios}
    problems: list[str] = []
    for sid, outcome in expected.items():
        if sid not in seen:
            problems.append(f"  {sid}: missing in Langfuse")
        elif seen[sid] != outcome:
            problems.append(f"  {sid}: record {outcome}, Langfuse {seen[sid]}")
    equal = sum(1 for sid, o in expected.items() if seen.get(sid) == o)
    present = sum(1 for sid in expected if sid in seen)
    ok = (
        len(experiments) == 1 and len(items) == len(expected) and equal == len(expected)
    )
    lines = [
        f"Experiments named {run.run_id}: {len(experiments)}",
        f"Items: {present} of {len(expected)} scenarios ({len(items)} items read)",
        f"Outcomes equal to the record: {equal} of {len(expected)}",
        *problems,
        "OK" if ok else "NOT OK",
    ]
    return ok, "\n".join(lines)


def http_fetch(base_url: str, public_key: str, secret_key: str) -> Fetch:
    import httpx2

    def fetch(path: str, params: dict[str, Any]) -> dict[str, Any]:
        response = httpx2.get(
            base_url.rstrip("/") + path,
            params=params,
            auth=(public_key, secret_key),
            timeout=20,
        )
        if response.status_code != 200:
            raise RuntimeError(f"GET {path} returned {response.status_code}")
        return response.json()

    return fetch


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.evals.langfuse_check")
    parser.add_argument("run", type=Path)
    parser.add_argument(
        "--wait", type=int, default=0, help="seconds to keep polling until it matches"
    )
    args = parser.parse_args(argv)
    run = read_run(args.run)
    if run is None:
        sys.stderr.write(f"Cannot read run file: {args.run}\n")
        return 1
    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY")
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY")
    if not public_key or not secret_key:
        sys.stderr.write("LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY must be set\n")
        return 1
    fetch = http_fetch(
        os.environ.get("LANGFUSE_BASE_URL") or DEFAULT_BASE_URL, public_key, secret_key
    )
    deadline = time.monotonic() + args.wait
    while True:
        ok, text = check(run, fetch)
        if ok or time.monotonic() >= deadline:
            break
        time.sleep(10)
    sys.stdout.write(text + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
