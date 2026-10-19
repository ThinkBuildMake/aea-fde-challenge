from pathlib import Path

import pytest

from app.settings import Settings


@pytest.fixture
def live(tmp_settings: Settings, seed_path: Path) -> Settings:
    tmp_settings.SCHEDULING_DB_PATH.parent.mkdir(parents=True)
    tmp_settings.SCHEDULING_DB_PATH.write_bytes(seed_path.read_bytes())
    return tmp_settings
