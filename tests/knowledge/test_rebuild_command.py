import json

import pytest

from app.knowledge import rebuild
from app.knowledge.embeddings import FakeEmbedder
from app.settings import Settings


@pytest.fixture
def env(kb_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Settings:
    for name, value in {
        "OPENROUTER_API_KEY": "test-key",
        "ADMIN_TOKEN": "test-admin-token",
        "SCHEDULING_DB_PATH": kb_settings.SCHEDULING_DB_PATH,
        "APP_DB_PATH": kb_settings.APP_DB_PATH,
        "INDEX_PATH": kb_settings.INDEX_PATH,
        "KB_DIR": kb_settings.KB_DIR,
    }.items():
        monkeypatch.setenv(name, str(value))
    return kb_settings


def test_command_prints_version_and_counts(env: Settings, capsys):
    assert rebuild.main(embedder=FakeEmbedder()) == 0
    printed = json.loads(capsys.readouterr().out)
    assert set(printed) == {"indexVersion", "passages", "sources"}
    assert printed["passages"] > 0 and printed["sources"] == 9
    manifest = json.loads((env.KB_DIR.parent / "kb_manifest.json").read_text())["files"]
    current = {rel for rel, e in manifest.items() if e["status"] == "current"}
    from app.knowledge.index import read_index

    loaded = read_index(env.INDEX_PATH)
    assert {p.source_file for p in loaded.passages} == current
    assert loaded.version == printed["indexVersion"]


def test_command_fails_on_unlisted_file(env: Settings, capsys):
    assert rebuild.main(embedder=FakeEmbedder()) == 0
    first = json.loads(capsys.readouterr().out)["indexVersion"]
    (env.KB_DIR / "faq" / "new_note.md").write_text("# New\nText")
    assert rebuild.main(embedder=FakeEmbedder()) == 1
    captured = capsys.readouterr()
    error = json.loads(captured.err)
    assert error["error"] == "manifest_invalid"
    assert "faq/new_note.md" in error["message"]
    from app.knowledge.index import read_index

    assert read_index(env.INDEX_PATH).version == first
