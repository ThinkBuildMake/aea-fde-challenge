import json
import shutil
from pathlib import Path

import pytest

from app.settings import Settings

REPO = Path(__file__).resolve().parent.parent
SEED = (
    REPO / "data" / "meridian_dataset" / "scheduling_db" / "meridian_scheduling.sqlite"
)
SCHEMA_MD = REPO / "data" / "meridian_dataset" / "scheduling_db" / "SCHEMA.md"
MIGRATIONS = REPO / "app" / "migrations"


@pytest.fixture
def seed_path() -> Path:
    return SEED


@pytest.fixture
def tmp_settings(tmp_path: Path) -> Settings:
    return Settings(
        OPENROUTER_API_KEY="test-key",  # type: ignore[arg-type]
        ADMIN_TOKEN="test-admin-token",  # type: ignore[arg-type]
        SCHEDULING_DB_PATH=tmp_path / "data" / "meridian_scheduling.sqlite",
        APP_DB_PATH=tmp_path / "data" / "app.sqlite",
        INDEX_PATH=tmp_path / "data" / "index" / "knowledge_index.npz",
    )


@pytest.fixture
def started(tmp_settings: Settings) -> Settings:
    from app.startup import run_startup

    run_startup(tmp_settings)
    return tmp_settings


STAMP = "2026-10-19"


@pytest.fixture
def kb_copy(tmp_path: Path) -> Path:
    """A copy of the knowledge base, manifest and extracted texts, with empty check stamps filled in."""
    dataset = REPO / "data" / "meridian_dataset"
    root = tmp_path / "kb"
    shutil.copytree(dataset / "knowledge_base", root / "knowledge_base")
    shutil.copytree(dataset / "kb_extracted", root / "kb_extracted")
    manifest = json.loads((dataset / "kb_manifest.json").read_text())
    for entry in manifest["files"].values():
        if "text" in entry and not entry["checkedOn"]:
            entry["checkedOn"] = STAMP
    (root / "kb_manifest.json").write_text(json.dumps(manifest, indent=2))
    for text in (root / "kb_extracted").rglob("*.txt"):
        lines = text.read_text().split("\n")
        for number, line in enumerate(lines):
            if line == "---":
                break
            if line in ("checkedBy:", "checkedOn:"):
                lines[number] = line + (
                    " test" if line == "checkedBy:" else f" {STAMP}"
                )
        text.write_text("\n".join(lines))
    return root


@pytest.fixture
def kb_settings(started: Settings, kb_copy: Path) -> Settings:
    return started.model_copy(update={"KB_DIR": kb_copy / "knowledge_base"})


@pytest.fixture(autouse=True)
def screen_says_safe(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    """The real danger screen runs everywhere; only its network call answers safe.
    Its own tests and S14's choose a verdict."""
    name = request.module.__name__
    if name.startswith(("tests.test_safety", "tests.test_interfaces")):
        return
    from app.safety.service import OpenRouterSafetyClassifier

    monkeypatch.setattr(
        OpenRouterSafetyClassifier,
        "classify",
        lambda self, messages, timeout_s: '{"verdict": "safe", "reason": "no_hazard"}',
    )


@pytest.fixture(autouse=True)
def key_usage_offline(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    """The gate never reaches OpenRouter's key usage; only the opt-in live test does."""
    if request.module.__name__.startswith(
        ("tests.test_spend_live", "tests.test_overview_spend")
    ):
        return
    from app.monitoring.spend import KeyUsageUnavailable, OpenRouterKeyUsage

    def offline(self: OpenRouterKeyUsage) -> float:
        raise KeyUsageUnavailable("offline in tests")

    monkeypatch.setattr(OpenRouterKeyUsage, "read", offline)


@pytest.fixture(autouse=True)
def langfuse_offline(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    """The gate never sends traces; only the opt-in live tests (modules ending in _live) may."""
    if request.module.__name__.endswith("_live"):
        return
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
