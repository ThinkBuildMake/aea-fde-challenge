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
