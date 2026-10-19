"""The exportEvalCandidates command: python -m app.monitoring.export <base_url> [--out DIR]"""

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
    candidates = response.json()["candidates"]
    args.out.mkdir(parents=True, exist_ok=True)
    written, skipped = 0, []
    for item in candidates:
        scenario_id = item["scenarioId"]
        if not SCENARIO_ID.match(scenario_id):
            skipped.append(scenario_id)
            continue
        text = json.dumps(item["scenario"], indent=2, sort_keys=True) + "\n"
        (args.out / f"{scenario_id}.json").write_text(text)
        written += 1
    summary: dict[str, object] = {"written": written, "out": str(args.out)}
    if skipped:
        summary["skipped"] = len(skipped)
    sys.stdout.write(json.dumps(summary) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
