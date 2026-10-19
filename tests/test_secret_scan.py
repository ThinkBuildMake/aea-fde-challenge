import os
import secrets
import shutil
import subprocess
from pathlib import Path

from tests.conftest import REPO


def gitleaks() -> str:
    binary = os.environ.get("GITLEAKS") or shutil.which("gitleaks")
    assert binary, "gitleaks is required: run `make tools` or set GITLEAKS"
    return binary


def git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def test_gitleaks_fails_on_a_committed_key(tmp_path: Path):
    git(tmp_path, "init", "-q")
    fake_key = "sk-or-v1-" + secrets.token_hex(
        32
    )  # built at runtime: no literal key in the repo
    (tmp_path / "config.py").write_text(f'OPENROUTER_API_KEY = "{fake_key}"\n')
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "add config")
    result = subprocess.run(
        [gitleaks(), "git", "--no-banner", "--exit-code", "1", str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1


def test_env_files_are_ignored_by_git():
    result = subprocess.run(
        ["git", "check-ignore", ".env"], cwd=REPO, check=False, capture_output=True
    )
    assert result.returncode == 0


def test_scan_gate_fails_when_gitleaks_could_not_read_the_history():
    env = {**os.environ, "GIT_DIR": "/nonexistent", "GITLEAKS": gitleaks()}
    result = subprocess.run(
        [str(REPO / "scripts" / "scan_secrets.sh")],
        check=False,
        cwd=REPO,
        env=env,
        capture_output=True,
    )
    assert result.returncode != 0
