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


def test_deploy_script_refuses_a_dirty_working_tree(tmp_path):
    import os
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "stray.txt").write_text("untracked")
    env = {
        "PATH": os.environ["PATH"],
        "RAILWAY_TOKEN": "t",
        "PUBLIC_URL": "https://example.invalid",
    }
    result = subprocess.run(
        ["bash", str(REPO / "scripts" / "deploy.sh")],
        check=False,
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "dirty" in result.stderr
