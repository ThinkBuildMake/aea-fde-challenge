from pathlib import Path

import pytest

from app.knowledge import extract
from app.knowledge.extract import ExtractError, extract_document, parse_header
from app.settings import Settings
from tests.conftest import REPO

EXTRACTED = REPO / "data" / "meridian_dataset" / "kb_extracted"


@pytest.fixture
def kb(tmp_path: Path, tmp_settings: Settings) -> Settings:
    kb_dir = tmp_path / "kb" / "knowledge_base"
    (kb_dir / "policies").mkdir(parents=True)
    (kb_dir / "policies" / "hours.png").write_bytes(b"png-bytes")
    (kb_dir / "policies" / "fees.pdf").write_bytes(b"pdf-bytes")
    (kb_dir / "policies" / "notes.md").write_text("# notes")
    return tmp_settings.model_copy(update={"KB_DIR": kb_dir})


def out_path(kb: Settings, rel: str) -> Path:
    return kb.KB_DIR.parent / "kb_extracted" / (rel + ".txt")


def test_text_is_written_with_an_unchecked_header(kb: Settings):
    seen = []

    def read(settings, path, data):
        seen.append(data)
        return "Closed July 4\n"

    path = extract_document(kb, Path("policies/hours.png"), read=read)
    assert path == out_path(kb, "policies/hours.png")
    header, body = parse_header(path.read_text())
    assert header["source"] == "policies/hours.png"
    assert header["model"] == extract.DOCUMENT_MODEL
    assert header["extractedOn"]
    assert header["checkedBy"] == "" and header["checkedOn"] == ""
    assert body == "Closed July 4\n"
    assert seen == [b"png-bytes"]


def test_png_sends_an_image_part_and_pdf_a_file_part():
    png = extract._content_parts(Path("a.png"), b"x")[1]
    pdf = extract._content_parts(Path("a.pdf"), b"x")[1]
    assert png["type"] == "image_url"
    assert png["image_url"]["url"].startswith("data:image/png;base64,")
    assert pdf["type"] == "file"
    assert pdf["file"]["file_data"].startswith("data:application/pdf;base64,")
    assert pdf["file"]["filename"] == "a.pdf"


def test_rerun_overwrites_unchecked_but_refuses_checked(kb: Settings):
    first = extract_document(kb, Path("policies/hours.png"), read=lambda *a: "one")
    extract_document(kb, Path("policies/hours.png"), read=lambda *a: "two")
    assert parse_header(first.read_text())[1].strip() == "two"
    checked = first.read_text().replace("checkedOn:", "checkedOn: 2026-10-19")
    first.write_text(checked)
    with pytest.raises(ExtractError, match="already checked"):
        extract_document(kb, Path("policies/hours.png"), read=lambda *a: "three")
    assert first.read_text() == checked


def test_a_failing_read_or_empty_text_writes_nothing(kb: Settings):
    def boom(*args):
        raise RuntimeError("secret detail")

    with pytest.raises(ExtractError) as error:
        extract_document(kb, Path("policies/hours.png"), read=boom)
    assert "secret detail" not in str(error.value)
    with pytest.raises(ExtractError):
        extract_document(kb, Path("policies/hours.png"), read=lambda *a: "  ")
    assert not out_path(kb, "policies/hours.png").exists()


def test_other_files_and_outside_paths_are_refused(kb: Settings, tmp_path: Path):
    with pytest.raises(ExtractError):
        extract_document(kb, Path("policies/notes.md"), read=lambda *a: "x")
    outside = tmp_path / "other.png"
    outside.write_bytes(b"x")
    with pytest.raises(ExtractError):
        extract_document(kb, outside, read=lambda *a: "x")


def test_main_exit_codes(kb: Settings, monkeypatch, capsys):
    for name in ("OPENROUTER_API_KEY", "ADMIN_TOKEN"):
        monkeypatch.setenv(name, "x")
    monkeypatch.setenv("SCHEDULING_DB_PATH", str(kb.SCHEDULING_DB_PATH))
    monkeypatch.setenv("APP_DB_PATH", str(kb.APP_DB_PATH))
    monkeypatch.setenv("INDEX_PATH", str(kb.INDEX_PATH))
    monkeypatch.setenv("KB_DIR", str(kb.KB_DIR))
    assert extract.main(["policies/hours.png"], read=lambda *a: "text") == 0
    assert capsys.readouterr().out.strip().endswith("hours.png.txt")
    assert extract.main(["policies/notes.md"], read=lambda *a: "text") == 1
    assert extract.main([]) == 2


def test_parse_header_round_trips():
    header, body = parse_header("a: 1\nb:\n---\nline\n---\nmore")
    assert header == {"a": "1", "b": ""}
    assert body == "line\n---\nmore"


def test_committed_texts_hold_the_facts_read_from_the_sources():
    holiday = (EXTRACTED / "policies" / "holiday_hours_2026.png.txt").read_text()
    for fact in ("Nov 26-27", "Dec 24", "$199"):
        assert fact in holiday
    fees = (EXTRACTED / "pricing" / "2026_fee_schedule.pdf.txt").read_text()
    for fact in ("Diagnostic visit", "$89", "$49", "$189", "$269", "$16.99"):
        assert fact in fees
