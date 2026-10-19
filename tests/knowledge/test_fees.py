import csv

import pytest

from app.knowledge.service import (
    IndexUnavailable,
    UnknownFee,
    get_fee,
    rebuild_index,
)
from app.settings import Settings
from app.types import Fee
from tests.knowledge.test_rebuild import make_ctx
from tests.knowledge.test_search import built, manifest_status

BOOK = "pricing/repair_price_book_2026.csv"


def test_diagnostic_fee_is_firm(kb_settings: Settings):
    ctx = built(kb_settings)
    assert get_fee(ctx, "FEE-DIAG") == Fee(
        code="FEE-DIAG", cents=8900, source_file=BOOK
    )
    assert manifest_status(kb_settings)[BOOK] == "current"


def test_late_change_fee_is_firm(kb_settings: Settings):
    fee = get_fee(built(kb_settings), "FEE-LATE")
    assert fee.cents == 4900
    assert manifest_status(kb_settings)[fee.source_file] == "current"


def test_unknown_fee_refused(kb_settings: Settings):
    ctx = built(kb_settings)
    for code in ("FEE-NONE", "FEE-PERMIT", "FEE-DISP", "fee-diag"):
        with pytest.raises(UnknownFee):
            get_fee(ctx, code)


def test_fee_needs_an_index(kb_settings: Settings):
    with pytest.raises(IndexUnavailable):
        get_fee(make_ctx(kb_settings), "FEE-DIAG")


def test_fee_amount_is_in_its_source_passage(kb_settings: Settings):
    ctx = built(kb_settings)
    loaded = ctx.index.current()
    assert loaded is not None
    for code in ("FEE-DIAG", "FEE-LATE", "FEE-AH", "FEE-HOL"):
        fee = get_fee(ctx, code)
        rows = [
            p
            for p in loaded.passages
            if p.kind == "price_row"
            and p.source_file == fee.source_file
            and f"sku: {code}\n" in p.text + "\n"
        ]
        assert len(rows) == 1
        assert str(fee.cents // 100) in rows[0].text

    path = kb_settings.KB_DIR / BOOK
    with path.open(newline="") as f:
        rows_in = list(csv.reader(f))
    for row in rows_in:
        if row[0] == "FEE-DIAG":
            row[3] = row[4] = "95"
    with path.open("w", newline="") as f:
        csv.writer(f).writerows(rows_in)
    rebuild_index(ctx)
    assert get_fee(ctx, "FEE-DIAG").cents == 9500
