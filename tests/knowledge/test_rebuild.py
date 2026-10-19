import csv
import json
import threading
from pathlib import Path

import pytest

from app.context import AppContext
from app.errors import AppError
from app.knowledge.embeddings import FakeEmbedder
from app.knowledge.service import rebuild_index
from app.main import create_app
from app.settings import Settings

NOT_SEARCHABLE = [
    "faq/faq_old_copy.md",
    "services/scheduling_guide.md",
    "policies/escalation_and_safety.md",
    "services/technician_arrival_and_etas.md",
    "services/duct_cleaning.md",
]
COLUMNS = [
    "sku",
    "description",
    "category",
    "low_price",
    "high_price",
    "member_discount_eligible",
    "notes",
]
HOLIDAY = "policies/holiday_hours_2026.png"
FEES = "pricing/2026_fee_schedule.pdf"


def make_ctx(settings: Settings, embedder: FakeEmbedder | None = None) -> AppContext:
    return create_app(settings, embedder=embedder or FakeEmbedder()).state.ctx


@pytest.fixture
def ctx(kb_settings: Settings) -> AppContext:
    return make_ctx(kb_settings)


def manifest_of(settings: Settings) -> dict:
    return json.loads((settings.KB_DIR.parent / "kb_manifest.json").read_text())[
        "files"
    ]


def sources(ctx: AppContext) -> set[str]:
    loaded = ctx.index.current()
    assert loaded is not None
    return {p.source_file for p in loaded.passages}


def test_build_holds_only_current_sources(ctx: AppContext):
    result = rebuild_index(ctx)
    current = {
        r for r, e in manifest_of(ctx.settings).items() if e["status"] == "current"
    }
    assert result.index_version.startswith("idx-")
    assert result.passages > 0
    assert result.sources == len(current) == 9
    assert sources(ctx) == current


def test_retired_and_staff_only_files_are_left_out(ctx: AppContext):
    rebuild_index(ctx)
    for source in sources(ctx):
        assert not source.startswith(("archive/", "internal/"))
        assert source not in NOT_SEARCHABLE


def test_unlisted_file_stops_the_build(ctx: AppContext):
    first = rebuild_index(ctx).index_version
    before = ctx.settings.INDEX_PATH.read_bytes()
    (ctx.settings.KB_DIR / "faq" / "new_note.md").write_text("# New\nText")
    with pytest.raises(AppError) as error:
        rebuild_index(ctx)
    assert error.value.status == 422 and error.value.code == "manifest_invalid"
    assert "faq/new_note.md" in error.value.message
    assert ctx.index.current().version == first  # type: ignore[union-attr]
    assert ctx.settings.INDEX_PATH.read_bytes() == before


def test_a_listed_file_that_is_missing_stops_the_build(ctx: AppContext):
    (ctx.settings.KB_DIR / "faq" / "customer_faq.md").unlink()
    with pytest.raises(AppError) as error:
        rebuild_index(ctx)
    assert error.value.code == "manifest_invalid"
    assert "customer_faq.md" in error.value.message


def test_image_and_pdf_become_passages(ctx: AppContext):
    rebuild_index(ctx)
    loaded = ctx.index.current()
    assert loaded is not None
    holiday = [p for p in loaded.passages if p.source_file == HOLIDAY]
    fees = [p for p in loaded.passages if p.source_file == FEES]
    assert holiday and all(p.kind == "image_text" for p in holiday)
    assert fees and all(p.kind == "pdf_text" for p in fees)
    assert "$199" in holiday[0].text
    assert "$89" in fees[0].text


def test_unchecked_text_is_refused(ctx: AppContext):
    first = rebuild_index(ctx).index_version
    text = ctx.settings.KB_DIR.parent / "kb_extracted" / (HOLIDAY + ".txt")
    lines = [
        "checkedOn:" if line.startswith("checkedOn:") else line
        for line in text.read_text().split("\n")
    ]
    text.write_text("\n".join(lines))
    with pytest.raises(AppError) as error:
        rebuild_index(ctx)
    assert error.value.status == 422 and error.value.code == "text_unchecked"
    assert HOLIDAY in error.value.message
    assert ctx.index.current().version == first  # type: ignore[union-attr]


def test_a_check_date_that_differs_from_the_manifest_is_refused(ctx: AppContext):
    path = ctx.settings.KB_DIR.parent / "kb_manifest.json"
    data = json.loads(path.read_text())
    data["files"][FEES]["checkedOn"] = None
    path.write_text(json.dumps(data))
    with pytest.raises(AppError) as error:
        rebuild_index(ctx)
    assert error.value.code == "text_unchecked" and FEES in error.value.message


def test_each_price_book_row_stays_whole(ctx: AppContext):
    rebuild_index(ctx)
    loaded = ctx.index.current()
    assert loaded is not None
    rows = [
        p
        for p in loaded.passages
        if p.source_file.endswith("repair_price_book_2026.csv")
    ]
    capacitor = [p for p in rows if p.section == "HV-CAP-01 Run capacitor replacement"]
    assert len(capacitor) == 1 and capacitor[0].kind == "price_row"
    for name in COLUMNS:
        assert name in capacitor[0].text
    assert "180" in capacitor[0].text and "260" in capacitor[0].text
    book = ctx.settings.KB_DIR / "pricing" / "repair_price_book_2026.csv"
    with book.open() as handle:
        assert len(rows) == len(list(csv.DictReader(handle)))
    assert all(p.kind == "price_row" for p in rows)


def test_failed_embedding_keeps_the_old_index(kb_settings: Settings):
    ctx = make_ctx(kb_settings)
    first = rebuild_index(ctx).index_version
    path = kb_settings.INDEX_PATH
    before = path.read_bytes()
    (kb_settings.KB_DIR / "faq" / "customer_faq.md").write_text("# Changed\nNew words")
    ctx.embedder = FakeEmbedder(fail=True)
    with pytest.raises(AppError) as error:
        rebuild_index(ctx)
    assert error.value.status == 502 and error.value.code == "embedding_failed"
    assert ctx.index.current().version == first  # type: ignore[union-attr]
    assert path.read_bytes() == before
    assert [p.name for p in path.parent.iterdir() if "tmp" in p.name] == []


def test_one_build_at_a_time(kb_settings: Settings):
    gate = threading.Event()
    slow = FakeEmbedder(gate=gate)
    first_ctx = make_ctx(kb_settings, slow)
    results = []
    worker = threading.Thread(target=lambda: results.append(rebuild_index(first_ctx)))
    worker.start()
    try:
        assert slow.entered.wait(timeout=10)
        for other in (first_ctx, make_ctx(kb_settings)):
            with pytest.raises(AppError) as error:
                rebuild_index(other)
            assert error.value.status == 409 and error.value.code == "build_in_progress"
    finally:
        gate.set()
        worker.join(timeout=10)
    assert len(results) == 1 and results[0].passages > 0
    assert first_ctx.index.current() is not None


def test_no_superseded_or_internal_text_is_indexed(ctx: AppContext):
    rebuild_index(ctx)
    loaded = ctx.index.current()
    assert loaded is not None
    everything = "\n".join(p.text for p in loaded.passages)
    for phrase in (
        "Diagnostic fee: $79",
        "48 hours notice",
        "90-day labor warranty",
        "$149 per year",
    ):
        assert phrase not in everything
    manifest = manifest_of(ctx.settings)
    current_lines = {
        line.strip()
        for rel, e in manifest.items()
        if e["status"] == "current" and rel.endswith((".md", ".csv"))
        for line in (ctx.settings.KB_DIR / rel).read_text().splitlines()
    }
    for rel, entry in manifest.items():
        if entry["status"] == "current":
            continue
        for line in (ctx.settings.KB_DIR / rel).read_text().splitlines():
            line = line.strip()
            if len(line) >= 15 and line not in current_lines:
                assert line not in everything, (rel, line)


def test_manifest_lists_every_supplied_file():
    from tests.conftest import REPO

    dataset = REPO / "data" / "meridian_dataset"
    listed = json.loads((dataset / "kb_manifest.json").read_text())["files"]
    on_disk = {
        p.relative_to(dataset / "knowledge_base").as_posix()
        for p in (dataset / "knowledge_base").rglob("*")
        if p.is_file()
    }
    assert set(listed) == on_disk
    for rel, entry in listed.items():
        if rel.startswith(("archive/", "internal/")) or rel in NOT_SEARCHABLE:
            assert entry["status"] != "current"


def test_same_input_gives_same_version(ctx: AppContext):
    assert rebuild_index(ctx).index_version == rebuild_index(ctx).index_version


def test_store_reloads_after_file_replaced(kb_settings: Settings):
    builder = make_ctx(kb_settings)
    server = make_ctx(kb_settings)
    assert server.index.current() is None
    first = rebuild_index(builder).index_version
    assert server.index.current().version == first  # type: ignore[union-attr]
    (kb_settings.KB_DIR / "faq" / "customer_faq.md").write_text("# Changed\nNew words")
    second = rebuild_index(builder).index_version
    assert second != first
    assert server.index.current().version == second  # type: ignore[union-attr]


def test_a_store_ignores_an_index_made_by_another_model(kb_settings: Settings):
    rebuild_index(make_ctx(kb_settings))

    class Other(FakeEmbedder):
        model = "other-model"

    assert make_ctx(kb_settings, Other()).index.current() is None


def test_a_damaged_index_file_is_not_loaded(kb_settings: Settings):
    ctx = make_ctx(kb_settings)
    rebuild_index(ctx)
    Path(kb_settings.INDEX_PATH).write_bytes(b"not an index")
    assert make_ctx(kb_settings).index.current() is None


@pytest.mark.parametrize("damage", [b"", b"PK\x03\x04truncated"])
def test_an_empty_or_truncated_index_file_keeps_the_last_good_index(
    kb_settings: Settings, damage: bytes
):
    ctx = make_ctx(kb_settings)
    version = rebuild_index(ctx).index_version
    kb_settings.INDEX_PATH.write_bytes(damage)
    assert ctx.index.current().version == version  # type: ignore[union-attr]
    assert ctx.index.current().version == version  # type: ignore[union-attr]
    assert make_ctx(kb_settings).index.current() is None


@pytest.mark.parametrize("bad", ["ragged", "text"])
def test_unusable_vectors_keep_the_old_index(kb_settings: Settings, bad: str):
    ctx = make_ctx(kb_settings)
    first = rebuild_index(ctx).index_version

    class Bad(FakeEmbedder):
        def embed(self, texts: list[str]) -> list[list[float]]:
            vectors = super().embed(texts)
            if bad == "ragged":
                vectors[0] = vectors[0][:3]
            else:
                vectors[0][0] = "x"  # type: ignore[assignment]
            return vectors

    (kb_settings.KB_DIR / "faq" / "customer_faq.md").write_text("# Changed\nNew words")
    ctx.embedder = Bad()
    with pytest.raises(AppError) as error:
        rebuild_index(ctx)
    assert error.value.status == 502 and error.value.code == "embedding_failed"
    assert ctx.index.current().version == first  # type: ignore[union-attr]


def test_an_index_whose_passages_do_not_match_their_hash_is_refused(
    kb_settings: Settings,
):
    import numpy as np

    ctx = make_ctx(kb_settings)
    rebuild_index(ctx)
    path = kb_settings.INDEX_PATH
    with np.load(path, allow_pickle=False) as data:
        vectors = data["vectors"]
        meta = json.loads(str(data["meta"]))
    assert len(meta["passages_sha256"]) == 64
    meta["passages"][0]["text"] += " tampered"
    with path.open("wb") as handle:
        np.savez(handle, vectors=vectors, meta=np.array(json.dumps(meta)))
    assert make_ctx(kb_settings).index.current() is None
