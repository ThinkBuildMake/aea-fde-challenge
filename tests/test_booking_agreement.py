import sqlite3
from contextlib import closing

import pytest

from app.context import AppContext
from app.main import create_app
from app.monitoring.agreement import booking_mismatches
from app.scheduling import service
from app.settings import Settings
from tests.test_overview import seed


@pytest.fixture
def ctx(started: Settings) -> AppContext:
    return create_app(started).state.ctx


@pytest.fixture
def cid(started: Settings) -> str:
    with closing(sqlite3.connect(started.APP_DB_PATH, isolation_level=None)) as db:
        return seed(db)


def sched(settings: Settings, sql: str, *args: object) -> list[tuple]:
    with closing(
        sqlite3.connect(settings.SCHEDULING_DB_PATH, isolation_level=None)
    ) as c:
        return c.execute(sql, args).fetchall()


def open_slot(settings: Settings, zone: str = "central", where: str = "") -> int:
    return sched(
        settings,
        "SELECT slot_id FROM appointment_slots WHERE status = 'open' AND zone = ? "
        "AND service_type <> 'estimate' AND slot_date >= '2026-10-16' "
        f"{where} ORDER BY slot_id LIMIT 1",
        zone,
    )[0][0]


def customer(settings: Settings, zone_city: str, tier: str = "none") -> str:
    return sched(
        settings,
        "SELECT customer_id FROM customers WHERE city = ? AND membership_tier = ? LIMIT 1",
        zone_city,
        tier,
    )[0][0]


def booked(ctx: AppContext, cid: str):
    who = customer(ctx.settings, "Austin")
    return service.book_visit(ctx, who, open_slot(ctx.settings), "no cool", cid)


def test_clean_after_book_and_cancel(ctx, cid):
    assert booking_mismatches(ctx) == 0
    visit = booked(ctx, cid)
    assert booking_mismatches(ctx) == 0
    who = customer(ctx.settings, "Austin")
    service.cancel_visit(ctx, who, visit.appointment_id, cid)
    assert booking_mismatches(ctx) == 0


def test_book_row_on_open_slot(ctx, cid):
    visit = booked(ctx, cid)
    sched(
        ctx.settings,
        "UPDATE appointment_slots SET status='open' WHERE slot_id=?",
        visit.slot_id,
    )
    assert booking_mismatches(ctx) == 1


def test_retired_row_ignored(ctx, cid):
    with closing(ctx.open_app_db()) as db:
        db.execute(
            "INSERT INTO visit_changes (conversation_id, action, appointment_id, slot_id, "
            "customer_id, retired_at) VALUES (?, 'book', 999, 1, 'MHC-10001', "
            "'2026-10-19T00:00:00.000Z')",
            (cid,),
        )
    assert booking_mismatches(ctx) == 0


def test_double_booked_slot(ctx, cid):
    visit = booked(ctx, cid)
    sched(
        ctx.settings,
        "INSERT INTO appointments (slot_id, customer_id, created_at, status) "
        "SELECT slot_id, customer_id, '2026-10-16', 'scheduled' FROM appointments "
        "WHERE appointment_id = ?",
        visit.appointment_id,
    )
    assert booking_mismatches(ctx) >= 1


def test_cancel_row_with_appointment_still_scheduled(ctx, cid):
    visit = booked(ctx, cid)
    who = customer(ctx.settings, "Austin")
    service.cancel_visit(ctx, who, visit.appointment_id, cid)
    sched(
        ctx.settings,
        "UPDATE appointments SET status='scheduled' WHERE appointment_id=?",
        visit.appointment_id,
    )
    assert booking_mismatches(ctx) == 1


def test_move_row_with_appointment_on_other_slot(ctx, cid):
    visit = booked(ctx, cid)
    who = customer(ctx.settings, "Austin")
    new = open_slot(ctx.settings)
    service.move_visit(ctx, who, visit.appointment_id, new, cid)
    assert booking_mismatches(ctx) == 0
    sched(
        ctx.settings,
        "UPDATE appointments SET slot_id=? WHERE appointment_id=?",
        visit.slot_id,
        visit.appointment_id,
    )
    assert booking_mismatches(ctx) == 1


def test_wrong_zone(ctx, cid):
    visit = booked(ctx, cid)
    sched(
        ctx.settings,
        "UPDATE appointment_slots SET zone='north' WHERE slot_id=?",
        visit.slot_id,
    )
    assert booking_mismatches(ctx) == 1


def test_wrong_technician(ctx, cid):
    visit = booked(ctx, cid)
    with closing(ctx.open_app_db()) as db:
        db.execute("UPDATE visit_changes SET confirmed_technician = 'Nobody'")
    assert booking_mismatches(ctx) == 1
    assert visit.appointment_id


def test_non_member_on_members_slot(ctx, cid):
    who = customer(ctx.settings, "Austin")
    slot = sched(
        ctx.settings,
        "SELECT slot_id FROM appointment_slots WHERE status='reserved_members' "
        "AND zone='central' AND service_type <> 'estimate' LIMIT 1",
    )[0][0]
    sched(
        ctx.settings,
        "UPDATE appointment_slots SET status='booked' WHERE slot_id=?",
        slot,
    )
    sched(
        ctx.settings,
        "INSERT INTO appointments (appointment_id, slot_id, customer_id, created_at, status) "
        "VALUES (160, ?, ?, '2026-10-16', 'scheduled')",
        slot,
        who,
    )
    assert booking_mismatches(ctx) == 1


def test_orphan_on_open_slot(ctx):
    who = customer(ctx.settings, "Austin")
    sched(
        ctx.settings,
        "INSERT INTO appointments (appointment_id, slot_id, customer_id, created_at, status) "
        "VALUES (160, ?, ?, '2026-10-16', 'scheduled')",
        open_slot(ctx.settings),
        who,
    )
    assert booking_mismatches(ctx) == 1
