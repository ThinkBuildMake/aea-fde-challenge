import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

REQUIRED = {
    "OPENROUTER_API_KEY": "dummy-key",
    "ADMIN_TOKEN": "dummy-admin",
    "SCHEDULING_DB_PATH": "/nonexistent/sched.sqlite",
    "APP_DB_PATH": "/nonexistent/app.sqlite",
    "INDEX_PATH": "/nonexistent/index.npz",
}


def run_app(env_overrides: dict[str, str | None]) -> subprocess.CompletedProcess[str]:
    env = {"PATH": os.environ["PATH"], **REQUIRED}
    for key, value in env_overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return subprocess.run(
        [sys.executable, "-m", "app"],
        check=False,
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_missing_openrouter_key_stops_start_and_names_it():
    result = run_app({"OPENROUTER_API_KEY": None})
    assert result.returncode == 1
    assert "OPENROUTER_API_KEY" in result.stderr
    assert "missing" in result.stderr.lower()


def test_missing_admin_token_stops_start_and_names_it():
    result = run_app({"ADMIN_TOKEN": None})
    assert result.returncode == 1
    assert "ADMIN_TOKEN" in result.stderr
    assert "OPENROUTER_API_KEY" not in result.stderr


def test_message_never_echoes_a_setting_value():
    result = run_app({"OPENROUTER_API_KEY": None})
    assert "dummy-admin" not in result.stderr + result.stdout


def test_empty_required_secret_stops_start_like_a_missing_one():
    result = run_app({"OPENROUTER_API_KEY": ""})
    assert result.returncode == 1
    assert "OPENROUTER_API_KEY" in result.stderr
    assert "Traceback" not in result.stderr


def test_unparseable_setting_prints_its_name_and_never_the_value():
    result = run_app({"MODEL_PRICES": "notjson-secret-ish"})
    assert result.returncode == 1
    assert "Invalid setting(s): MODEL_PRICES" in result.stderr
    assert "Traceback" not in result.stderr
    assert "notjson-secret-ish" not in result.stderr + result.stdout
