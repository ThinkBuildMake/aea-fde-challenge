"""The manifest: which knowledge-base files may be searched. A status is a decision, never a filename pattern."""

import json
from dataclasses import dataclass
from pathlib import Path

from app.errors import AppError

STATUSES = ("current", "superseded", "agent-only", "placeholder")
MANIFEST_NAME = "kb_manifest.json"


@dataclass(frozen=True)
class Entry:
    status: str
    reason: str
    text: str | None = None
    checked_on: str | None = None


def manifest_path(kb_dir: Path) -> Path:
    return kb_dir.parent / MANIFEST_NAME


def load_manifest(kb_dir: Path) -> dict[str, Entry]:
    path = manifest_path(kb_dir)
    try:
        raw = json.loads(path.read_text())["files"]
        return {
            rel: Entry(
                status=str(item["status"]),
                reason=str(item.get("reason", "")),
                text=item.get("text"),
                checked_on=item.get("checkedOn"),
            )
            for rel, item in raw.items()
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise AppError(
            422, "manifest_invalid", f"The manifest {path.name} cannot be read."
        ) from error


def check_manifest(kb_dir: Path, manifest: dict[str, Entry]) -> None:
    """Every file in the folder must be listed, every listed file must exist, every status known."""
    on_disk = {
        p.relative_to(kb_dir).as_posix() for p in kb_dir.rglob("*") if p.is_file()
    }
    unlisted = sorted(on_disk - manifest.keys())
    missing = sorted(manifest.keys() - on_disk)
    unknown = sorted(rel for rel, e in manifest.items() if e.status not in STATUSES)
    problems = []
    if unlisted:
        problems.append("not in the manifest: " + ", ".join(unlisted))
    if missing:
        problems.append("listed but missing: " + ", ".join(missing))
    if unknown:
        problems.append("unknown status: " + ", ".join(unknown))
    if problems:
        raise AppError(422, "manifest_invalid", "; ".join(problems))
