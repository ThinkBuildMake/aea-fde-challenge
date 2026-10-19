"""The resetScheduling command: python -m app.scheduling.reset"""

import json
import sys

from app.errors import AppError
from app.main import create_app
from app.scheduling.service import reset_scheduling
from app.settings import load_settings_or_exit
from app.types import ResetSchedulingResult


def main() -> int:
    settings = load_settings_or_exit()
    ctx = create_app(settings).state.ctx
    try:
        result = reset_scheduling(ctx)
    except AppError as error:
        sys.stderr.write(
            json.dumps({"error": error.code, "message": error.message}) + "\n"
        )
        return 1
    body = ResetSchedulingResult(
        restored=True, snapshot_id=result.snapshot_id, slot_counts=result.slot_counts
    )
    sys.stdout.write(json.dumps(body.model_dump(by_alias=True)) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
