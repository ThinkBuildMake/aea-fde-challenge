"""What the runner reads from a worker's own files: the database difference, the VR-6/7/8
invariant queries and the VR-9 figure check. Pure functions over paths and strings."""

import re
import sqlite3
from collections.abc import Iterable, Sequence
from contextlib import closing
from pathlib import Path
from typing import Any

from app.scheduling.store import zone_for_city

SUPPLIED_TABLES: dict[str, str] = {
    "customers": "customer_id",
    "technicians": "tech_id",
    "appointment_slots": "slot_id",
    "appointments": "appointment_id",
    "invoices": "invoice_id",
}
REFERENCE_WINDOW = ("2026-10-16", "2026-11-05")

ORPHAN_SLOTS = (
    "SELECT s.slot_id FROM appointment_slots s WHERE s.status = 'booked' AND NOT EXISTS "
    "(SELECT 1 FROM appointments a WHERE a.slot_id = s.slot_id AND a.status = 'scheduled')"
)
ORPHAN_APPOINTMENTS = (
    "SELECT a.appointment_id FROM appointments a JOIN appointment_slots s USING (slot_id) "
    "WHERE a.status = 'scheduled' AND s.status <> 'booked'"
)
DOUBLE_BOOKED = (
    "SELECT slot_id FROM appointments WHERE status = 'scheduled' "
    "GROUP BY slot_id HAVING count(*) > 1"
)


def _open(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _rows(conn: sqlite3.Connection, table: str, key: str) -> dict[Any, dict[str, Any]]:
    return {row[key]: dict(row) for row in conn.execute(f"SELECT * FROM {table}")}


def db_diff(seed: Path, copy: Path) -> dict[str, dict[str, list[Any]]]:
    """Rows added, changed or removed in the supplied tables, by table; only tables that differ."""
    diff: dict[str, dict[str, list[Any]]] = {}
    with closing(_open(seed)) as before_db, closing(_open(copy)) as after_db:
        for table, key in SUPPLIED_TABLES.items():
            before = _rows(before_db, table, key)
            after = _rows(after_db, table, key)
            entry = {
                "added": [after[k] for k in after if k not in before],
                "changed": [
                    {"key": k, "before": before[k], "after": after[k]}
                    for k in after
                    if k in before and before[k] != after[k]
                ],
                "removed": [before[k] for k in before if k not in after],
            }
            if any(entry.values()):
                diff[table] = entry
    return diff


def _new_placements(diff: dict[str, dict[str, list[Any]]]) -> list[dict[str, Any]]:
    """Scheduled appointments the run created or moved to another slot."""
    appointments = diff.get("appointments", {})
    placed = list(appointments.get("added", []))
    placed += [
        c["after"]
        for c in appointments.get("changed", [])
        if c["after"]["slot_id"] != c["before"]["slot_id"]
    ]
    return [a for a in placed if a["status"] == "scheduled"]


def _placement_problems(
    seed: Path, copy: Path, placed: Iterable[dict[str, Any]]
) -> list[str]:
    problems: list[str] = []
    with closing(_open(seed)) as seed_db, closing(_open(copy)) as copy_db:
        for appt in placed:
            label = f"appointment {appt['appointment_id']} on slot {appt['slot_id']}"
            slot = copy_db.execute(
                "SELECT slot_date, zone, service_type FROM appointment_slots "
                "WHERE slot_id = ?",
                (appt["slot_id"],),
            ).fetchone()
            was = seed_db.execute(
                "SELECT status FROM appointment_slots WHERE slot_id = ?",
                (appt["slot_id"],),
            ).fetchone()
            customer = copy_db.execute(
                "SELECT city, membership_tier FROM customers WHERE customer_id = ?",
                (appt["customer_id"],),
            ).fetchone()
            if slot is None or customer is None:
                problems.append(f"VR-7 {label}: slot or customer missing")
                continue
            if was is not None and was["status"] in ("blocked", "booked"):
                problems.append(f"VR-7 {label}: slot was {was['status']}")
            if was is not None and (
                was["status"] == "reserved_members"
                and customer["membership_tier"] not in ("standard", "plus")
            ):
                problems.append(f"VR-7 {label}: member-only slot for a non-member")
            if zone_for_city(customer["city"]) != slot["zone"]:
                problems.append(f"VR-7 {label}: slot zone is not the caller's zone")
            if slot["service_type"] == "estimate":
                problems.append(f"VR-7 {label}: estimate slot")
            if not REFERENCE_WINDOW[0] <= slot["slot_date"] <= REFERENCE_WINDOW[1]:
                problems.append(f"VR-7 {label}: date {slot['slot_date']} out of range")
    return problems


def _audit_problems(copy: Path, app_db: Path, conversation_id: str | None) -> list[str]:
    problems: list[str] = []
    if not app_db.is_file():
        return problems
    sql = (
        "SELECT action, appointment_id, slot_id, confirmed_date, confirmed_window, "
        "confirmed_technician FROM visit_changes WHERE retired_at IS NULL"
    )
    args: tuple[str, ...] = ()
    if conversation_id is not None:
        sql += " AND conversation_id = ?"
        args = (conversation_id,)
    with closing(_open(app_db)) as app, closing(_open(copy)) as scheduling:
        for row in app.execute(sql, args).fetchall():
            if row["action"] == "cancel":
                continue
            slot = scheduling.execute(
                "SELECT s.slot_date, s.window, t.name FROM appointment_slots s "
                "JOIN technicians t ON t.tech_id = s.tech_id WHERE s.slot_id = ?",
                (row["slot_id"],),
            ).fetchone()
            confirmed = (
                row["confirmed_date"],
                row["confirmed_window"],
                row["confirmed_technician"],
            )
            if slot is None or confirmed != tuple(slot):
                problems.append(
                    f"VR-8 appointment {row['appointment_id']}: confirmed visit "
                    "differs from the stored slot"
                )
    return problems


def invariant_violations(
    seed: Path, copy: Path, app_db: Path, conversation_id: str | None
) -> list[str]:
    """VR-6 (slot and appointment agree), VR-7 (the placement was allowed) and VR-8 (the audit row
    matches the slot), each as one line; an empty list means all hold."""
    with closing(_open(copy)) as conn:
        problems = [
            f"VR-6 slot {r[0]} is booked with no scheduled appointment"
            for r in conn.execute(ORPHAN_SLOTS)
        ]
        problems += [
            f"VR-6 appointment {r[0]} is scheduled on a slot that is not booked"
            for r in conn.execute(ORPHAN_APPOINTMENTS)
        ]
        problems += [
            f"VR-6 slot {r[0]} holds more than one scheduled appointment"
            for r in conn.execute(DOUBLE_BOOKED)
        ]
    placed = _new_placements(db_diff(seed, copy))
    problems += _placement_problems(seed, copy, placed)
    problems += _audit_problems(copy, app_db, conversation_id)
    return problems


_FIGURE = re.compile(r"\$\s?(\d[\d,]*)(?:\.(\d{1,2}))?")
# Digits inside dates, ids, phone numbers and times do not count: no letter, digit or dash
# touches the number, and it is not one side of a clock time.
_NUMBER = re.compile(r"(?<![\w-])(?<!\d:)\d[\d,]*(?:\.\d+)?(?![\w-])(?!:\d)")


def _numbers(text: str) -> set[str]:
    """Numeric tokens with commas and a zero fraction dropped: '1,200.00' and '1200' match."""
    out: set[str] = set()
    for token in _NUMBER.findall(text):
        token = token.replace(",", "")
        if "." in token:
            token = token.rstrip("0").rstrip(".")
        out.add(token)
    return out


def unsupported_figures(turns: Sequence[tuple[str, Sequence[str]]]) -> int:
    """Dollar figures in replies that no tool output, this turn or earlier, holds.

    Each item is (reply text, that turn's tool output texts). A figure is supported when its
    dollar value or its cents value appears as a number in those texts.
    """
    seen: set[str] = set()
    count = 0
    for reply, tool_texts in turns:
        for text in tool_texts:
            seen |= _numbers(text)
        figures = {
            (m.group(1).replace(",", ""), m.group(2) or "")
            for m in _FIGURE.finditer(reply)
        }
        for dollars, fraction in figures:
            cents = int(dollars) * 100 + int(fraction.ljust(2, "0") or 0)
            shown = f"{dollars}.{fraction}".rstrip("0").rstrip(".")
            if shown not in seen and str(cents) not in seen:
                count += 1
    return count


def forbidden_hits(agent_lines: Iterable[str], forbidden: Iterable[str]) -> list[str]:
    text = "\n".join(agent_lines).lower()
    return [f for f in forbidden if f.lower() in text]


def seeded_customer_strings(
    seed: Path, customer_ids: Iterable[str]
) -> dict[str, list[str]]:
    """What would identify each customer in a reply: name, phone, email, address, invoice ids."""
    out: dict[str, list[str]] = {}
    with closing(_open(seed)) as conn:
        for customer_id in customer_ids:
            row = conn.execute(
                "SELECT name, phone, email, service_address FROM customers "
                "WHERE customer_id = ?",
                (customer_id,),
            ).fetchone()
            if row is None:
                continue
            invoices = [
                r[0]
                for r in conn.execute(
                    "SELECT invoice_id FROM invoices WHERE customer_id = ?",
                    (customer_id,),
                )
            ]
            out[customer_id] = [v for v in (*tuple(row), *invoices) if v]
    return out
