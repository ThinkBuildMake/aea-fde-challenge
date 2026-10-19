import json

from app.settings import REPO_ROOT, Settings
from tests.conftest import REPO


def test_railway_config_points_at_the_dockerfile_and_health_path():
    config = json.loads((REPO / "railway.json").read_text())
    assert config["build"]["builder"] == "DOCKERFILE"
    assert config["deploy"]["healthcheckPath"] == "/health"


def test_dockerfile_runs_the_app_and_ships_the_seed_without_a_volume_line():
    text = (REPO / "Dockerfile").read_text()
    assert 'CMD ["python", "-m", "app"]' in text
    assert "VOLUME" not in text
    seed_dir = Settings.model_fields["SEED_DB_PATH"].default.parent.relative_to(
        REPO_ROOT
    )
    assert f"COPY {seed_dir}/ {seed_dir}/" in text


def test_dockerignore_excludes_env_files():
    assert ".env*" in (REPO / ".dockerignore").read_text().splitlines()
