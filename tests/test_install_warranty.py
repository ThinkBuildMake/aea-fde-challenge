"""S51: the identify match says whether the 2-year install labor warranty has ended."""

import pytest

from app.settings import Settings
from tests.test_agent_tools import customer, identify, run, stub, tool_results


def matched(started: Settings, monkeypatch: pytest.MonkeyPatch, install: str | None):
    ref = customer("MHC-10002").model_copy(update={"system_install_date": install})
    stub(monkeypatch, "app.scheduling.service.identify_customer", ref)
    cid, _ = run(started, identify("MHC-10002"), texts=["I'm Test, 555-0100"])
    (out,) = [r for r in tool_results(started, cid) if "customer" in r]
    print("match:", out)
    return out["customer"]


@pytest.mark.parametrize(
    ("install", "ends", "ended"),
    [
        ("2023-02-17", "2025-02-17", True),
        ("2025-03-01", "2027-03-01", False),
        ("2024-02-29", "2026-02-28", True),
        # Today is the reference date 2026-10-16, not the wall clock.
        ("2024-10-16", "2026-10-16", False),
        ("2024-10-17", "2026-10-17", False),
    ],
)
def test_match_gives_the_install_labor_warranty_end(
    started: Settings,
    monkeypatch: pytest.MonkeyPatch,
    install: str,
    ends: str,
    ended: bool,
):
    match = matched(started, monkeypatch, install)
    assert match["installLaborWarrantyEnds"] == ends
    assert match["installLaborWarrantyEnded"] is ended


@pytest.mark.parametrize("install", [None, "2023/02/17"])
def test_no_usable_install_date_gives_no_warranty_fields(
    started: Settings, monkeypatch: pytest.MonkeyPatch, install: str | None
):
    match = matched(started, monkeypatch, install)
    assert "installLaborWarrantyEnds" not in match
    assert "installLaborWarrantyEnded" not in match
