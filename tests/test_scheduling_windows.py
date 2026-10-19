import sqlite3
from collections.abc import Iterator

import pytest

from app.context import AppContext
from app.main import create_app
from app.scheduling.service import (
    AppointmentNotFound,
    SchedulingUnavailable,
    find_open_windows,
    get_appointment,
    list_appointments,
    scheduling_status,
)
from app.settings import Settings
from app.types import AppointmentView


@pytest.fixture
def ctx(started: Settings) -> AppContext:
    return create_app(started).state.ctx


@pytest.fixture
def db(started: Settings) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(started.SCHEDULING_DB_PATH)
    yield connection
    connection.close()


def test_non_member_first_window_skips_member_only(ctx: AppContext):
    result = find_open_windows(ctx, "MHC-10004", "hvac_repair")
    first = result.windows[0]
    assert (first.slot_id, first.date, first.window) == (
        56,
        "2026-10-19",
        "08:00-12:00",
    )
    assert first.technician_name == "Marta Kowalski"
    assert first.member_only is False
    assert 1 not in [w.slot_id for w in result.windows]
    assert result.matched_request is True
    assert result.reason is None


def test_member_sees_member_only_slot_first(ctx: AppContext):
    first = find_open_windows(ctx, "MHC-10001", "hvac_repair").windows[0]
    assert (first.slot_id, first.date, first.window) == (1, "2026-10-16", "08:00-12:00")
    assert first.technician_name == "Ray Mendoza"
    assert first.member_only is True
    assert first.zone == "north"
    assert first.service_type == "hvac_repair"


def test_no_plumber_in_north_zone(ctx: AppContext):
    result = find_open_windows(ctx, "MHC-10004", "plumbing")
    assert result.windows == []
    assert result.reason == "no_plumber_in_zone"
    assert result.matched_request is False


def test_city_without_zone(ctx: AppContext, db: sqlite3.Connection):
    cols = [r[1] for r in db.execute("PRAGMA table_info(customers)")]
    row = dict(
        zip(
            cols,
            db.execute(
                "SELECT * FROM customers WHERE customer_id = 'MHC-10004'"
            ).fetchone(),
        )
    )
    row.update(customer_id="MHC-90001", city="Manor", membership_tier="none")
    db.execute(
        f"INSERT INTO customers ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        [row[c] for c in cols],
    )
    db.commit()
    result = find_open_windows(ctx, "MHC-90001", "hvac_repair")
    assert result.windows == []
    assert result.reason == "city_not_in_zone_map"


def test_unknown_customer(ctx: AppContext):
    result = find_open_windows(ctx, "MHC-00000", "hvac_repair")
    assert result.windows == [] and result.reason == "unknown_customer"


def test_nothing_before_reference_date(ctx: AppContext, started: Settings):
    ctx.settings = started.model_copy(update={"REFERENCE_DATE": "2026-10-18"})
    windows = find_open_windows(ctx, "MHC-10001", "hvac_repair").windows
    assert windows
    assert all(w.date >= "2026-10-18" for w in windows)
    assert 1 not in [w.slot_id for w in windows]


def test_visit_on_file(ctx: AppContext):
    expected = AppointmentView(
        appointment_id=159,
        date="2026-10-22",
        window="08:00-12:00",
        technician_name="Marta Kowalski",
        service_type="hvac_repair",
        zone="north",
        issue="AC blowing warm air",
        late_cancel_fee_applies=False,
    )
    assert list_appointments(ctx, "MHC-10001") == [expected]
    assert get_appointment(ctx, "MHC-10001", 159) == expected


def test_late_cancel_fee_inside_24_hours(ctx: AppContext, started: Settings):
    ctx.settings = started.model_copy(update={"REFERENCE_DATE": "2026-10-21"})
    assert list_appointments(ctx, "MHC-10001")[0].late_cancel_fee_applies is True


def test_other_customers_visit_not_found(ctx: AppContext):
    with pytest.raises(AppointmentNotFound):
        get_appointment(ctx, "MHC-10002", 159)
    assert 159 not in [a.appointment_id for a in list_appointments(ctx, "MHC-10002")]


def test_unreadable_file_reported(ctx: AppContext, started: Settings):
    assert scheduling_status(ctx) == "ok"
    started.SCHEDULING_DB_PATH.write_bytes(b"not a database" * 100)
    with pytest.raises(SchedulingUnavailable):
        find_open_windows(ctx, "MHC-10001", "hvac_repair")
    assert scheduling_status(ctx) == "error"


def test_missing_file_reported_without_creating_it(ctx: AppContext, started: Settings):
    started.SCHEDULING_DB_PATH.unlink()
    assert scheduling_status(ctx) == "error"
    assert not started.SCHEDULING_DB_PATH.exists()


def test_day_without_window_gets_nearest(ctx: AppContext):
    miss = find_open_windows(
        ctx, "MHC-10004", "hvac_repair", preferred_date="2026-10-18"
    )
    assert miss.matched_request is False
    first = miss.windows[0]
    assert (first.slot_id, first.date, first.window) == (
        56,
        "2026-10-19",
        "08:00-12:00",
    )
    assert first.technician_name == "Marta Kowalski"
    hit = find_open_windows(
        ctx, "MHC-10004", "hvac_repair", preferred_date="2026-10-19"
    )
    assert hit.matched_request is True
    assert hit.windows and all(w.date == "2026-10-19" for w in hit.windows)


@pytest.mark.parametrize("customer_id", ["MHC-10004", "MHC-10001"])
@pytest.mark.parametrize("service_type", ["hvac_repair", "hvac_tune_up"])
def test_vr7_every_window_is_bookable_by_that_customer(
    ctx: AppContext,
    started: Settings,
    db: sqlite3.Connection,
    customer_id: str,
    service_type: str,
):
    member = customer_id == "MHC-10001"
    windows = find_open_windows(ctx, customer_id, service_type).windows
    assert windows
    for w in windows:
        slot_date, zone, stype, status = db.execute(
            "SELECT slot_date, zone, service_type, status FROM appointment_slots "
            "WHERE slot_id = ?",
            (w.slot_id,),
        ).fetchone()
        assert zone == "north" and stype == service_type
        assert slot_date >= started.REFERENCE_DATE
        assert status in (("open", "reserved_members") if member else ("open",))
        assert w.member_only == (status == "reserved_members")
    assert find_open_windows(ctx, customer_id, "estimate").windows == []


def test_missing_file_raises_and_is_not_created(ctx: AppContext, started: Settings):
    from app.scheduling.service import identify_customer

    started.SCHEDULING_DB_PATH.unlink()
    with pytest.raises(SchedulingUnavailable):
        find_open_windows(ctx, "MHC-10001", "hvac_repair")
    with pytest.raises(SchedulingUnavailable):
        identify_customer(ctx, "Linda Foster", phone="512-555-0101")
    assert not started.SCHEDULING_DB_PATH.exists()


def test_non_iso_preferred_date_is_no_preference(ctx: AppContext):
    result = find_open_windows(
        ctx, "MHC-10004", "hvac_repair", preferred_date="next tuesday"
    )
    assert result.windows
    assert result.matched_request is False
    plain = find_open_windows(ctx, "MHC-10004", "hvac_repair")
    assert [w.slot_id for w in result.windows] == [w.slot_id for w in plain.windows]
