"""The exportEvalCandidates command, the one documented way to pull drafts into the repo:

    ADMIN_TOKEN=... uv run python -m app.monitoring.export <base_url> [--out DIR]

It reads GET /admin/eval-candidates and writes eval/candidates/CAND-xxxxxxxx.json per
draft. On any failure it writes nothing and says why on stderr.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

import httpx2

SCENARIO_ID = re.compile(r"^CAND-[0-9a-f]{8}$")


def _fail(code: str, message: str) -> int:
    sys.stderr.write(json.dumps({"error": code, "message": message}) + "\n")
    return 1


def _drafts(response: httpx2.Response) -> list[tuple[str, dict]] | None:
    """Every (scenarioId, scenario) pair, or None when the answer is not a list of drafts."""
    try:
        body = response.json()
    except ValueError:
        return None
    items = body.get("candidates") if isinstance(body, dict) else None
    if not isinstance(items, list):
        return None
    drafts = []
    for item in items:
        if not (
            isinstance(item, dict)
            and isinstance(item.get("scenarioId"), str)
            and isinstance(item.get("scenario"), dict)
        ):
            return None
        drafts.append((item["scenarioId"], item["scenario"]))
    return drafts


def main(argv: list[str] | None = None, client: httpx2.Client | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.monitoring.export")
    parser.add_argument("base_url")
    parser.add_argument("--out", type=Path, default=Path("eval/candidates"))
    args = parser.parse_args(argv)
    token = os.environ.get("ADMIN_TOKEN", "")
    if not token:
        return _fail("missing_token", "Set ADMIN_TOKEN to the app's admin token.")
    owned = client is None
    http = client or httpx2.Client(timeout=30)
    try:
        response = http.get(
            args.base_url.rstrip("/") + "/admin/eval-candidates",
            headers={"Authorization": f"Bearer {token}"},
        )
    except httpx2.HTTPError:
        return _fail("unreachable", "The app could not be reached.")
    finally:
        if owned:
            http.close()
    if response.status_code != 200:
        error = "unauthorized" if response.status_code == 401 else "export_failed"
        return _fail(error, f"The app answered {response.status_code}.")
    drafts = _drafts(response)
    if drafts is None:
        return _fail(
            "export_failed", "The app answered 200 but not with a list of drafts."
        )
    args.out.mkdir(parents=True, exist_ok=True)
    written, skipped = 0, []
    for scenario_id, scenario in drafts:
        if not SCENARIO_ID.match(scenario_id):
            skipped.append(scenario_id)
            continue
        text = json.dumps(scenario, indent=2, sort_keys=True) + "\n"
        (args.out / f"{scenario_id}.json").write_text(text)
        written += 1
    summary: dict[str, object] = {"written": written, "out": str(args.out)}
    if skipped:
        summary["skipped"] = len(skipped)
    sys.stdout.write(json.dumps(summary) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
