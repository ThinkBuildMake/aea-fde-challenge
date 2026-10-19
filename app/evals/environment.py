"""DE-3: the run record names the models and their versions, the index version, the database
snapshot and the app commit."""

import hashlib
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

import httpx2

from app.evals.records import RunEnvironment
from app.knowledge.index import read_index
from app.settings import REPO_ROOT, Settings

OPENROUTER_LISTINGS = (
    "https://openrouter.ai/api/v1/models",
    "https://openrouter.ai/api/v1/embeddings/models",
)
UNREPORTED = "unreported"

VersionLookup = Callable[[Sequence[str]], dict[str, str]]


def openrouter_versions(slugs: Sequence[str]) -> dict[str, str]:
    """Each slug's canonical (dated) slug as the provider lists it; 'unreported' when it cannot."""
    canonical: dict[str, str] = {}
    for url in OPENROUTER_LISTINGS:
        try:
            response = httpx2.get(url, timeout=10)
            response.raise_for_status()
            for item in response.json().get("data", []):
                slug = item.get("canonical_slug") or item.get("id")
                canonical[item.get("id")] = slug
                canonical[slug] = slug
        except Exception:  # noqa: BLE001,S112 - a lookup failure never stops a run
            continue
    return {slug: canonical.get(slug, UNREPORTED) for slug in slugs}


def _git(*args: str) -> str | None:
    try:
        done = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip()


def app_commit() -> str:
    head = _git("rev-parse", "HEAD")
    if not head:
        return "unknown"
    return head + ("-dirty" if _git("status", "--porcelain") else "")


def snapshot_id(seed: Path) -> str:
    return "sha256:" + hashlib.sha256(seed.read_bytes()).hexdigest()


def index_version(index: Path) -> str:
    try:
        return read_index(index).version
    except Exception:  # noqa: BLE001 - no index yet is a fact to record, not a failure
        return "none"


def describe_environment(
    settings: Settings,
    seed: Path,
    index: Path,
    versions: VersionLookup = openrouter_versions,
) -> RunEnvironment:
    slugs = [
        settings.AGENT_MODEL,
        settings.SAFETY_MODEL,
        settings.CALLER_MODEL,
        settings.JUDGE_MODEL,
        settings.EMBEDDING_MODEL,
    ]
    return RunEnvironment(
        agent_model=settings.AGENT_MODEL,
        safety_model=settings.SAFETY_MODEL,
        caller_model=settings.CALLER_MODEL,
        judge_model=settings.JUDGE_MODEL,
        embedding_model=settings.EMBEDDING_MODEL,
        model_versions=versions(list(dict.fromkeys(slugs))),
        kb_index_version=index_version(index),
        db_snapshot_id=snapshot_id(seed),
        app_commit=app_commit(),
    )
