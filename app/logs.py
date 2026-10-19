import json
import re
import sys

_DIGIT_RUN = re.compile(r"\d(?:[ -]?\d){12,}")


def mask_digit_runs(text: str) -> str:
    return _DIGIT_RUN.sub("[digits removed]", text)


def log_event(event: str, **fields: str | float | bool | None) -> None:
    """Write one JSON line to stdout; any run of 13+ digits is masked."""
    safe = {
        k: mask_digit_runs(v) if isinstance(v, str) else v for k, v in fields.items()
    }
    sys.stdout.write(json.dumps({"event": mask_digit_runs(event), **safe}) + "\n")
    sys.stdout.flush()
