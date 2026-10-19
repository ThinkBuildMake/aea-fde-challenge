import re
import sqlite3
from pathlib import Path

from app.settings import Settings
from app.startup import run_startup
from tests.conftest import SCHEMA_MD, SEED

APP_TABLES = {
    "conversations",
    "turns",
    "handoffs",
    "waitlist_entries",
    "flags",
    "eval_candidates",
    "visit_changes",
}


def parse_schema_md(path: Path) -> dict[str, set[str]]:
    """Table name -> column names that SCHEMA.md names."""
    tables: dict[str, set[str]] = {}
    current: str | None = None
    for line in path.read_text().splitlines():
        heading = re.match(r"^### (\w+)\s*$", line)
        if heading:
            current = heading.group(1)
            tables[current] = set()
            continue
        if line.startswith("## "):
            current = None
            continue
        if current is None or not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if current == "technicians":
            if cells and cells[0] == "tech_id":
                tables[current] = {re.sub(r"\s*\(.*", "", cell) for cell in cells}
            continue
        first = cells[0]
        if first in ("column", "") or set(first) <= {"-"}:
            continue
        for name in first.split(","):
            name = name.split("/")[0].strip()
            if re.fullmatch(r"\w+", name):
                tables[current].add(name)
    return tables


def snapshot(path: Path) -> dict[str, object]:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    master = conn.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
    ).fetchall()
    info = {
        row[0]: conn.execute(f"PRAGMA table_info({row[0]})").fetchall()
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()
    return {"master": master, "info": info}


def diff_count(path: Path) -> int:
    doc = parse_schema_md(SCHEMA_MD)
    actual = snapshot(path)
    info: dict[str, list[tuple]] = actual["info"]  # type: ignore[assignment]
    count = 0
    for table, columns in doc.items():
        present = {row[1] for row in info.get(table, [])}
        count += len(columns - present) if table in info else 1 + len(columns)
    count += len(set(info) - set(doc))
    seed = snapshot(SEED)
    if actual["master"] != seed["master"]:
        count += 1
    if actual["info"] != seed["info"]:
        count += 1
    return count


def test_schema_md_parser_reads_the_documented_tables():
    doc = parse_schema_md(SCHEMA_MD)
    assert set(doc) == {
        "customers",
        "technicians",
        "appointment_slots",
        "appointments",
        "invoices",
    }
    assert {"customer_id", "membership_tier"} <= doc["customers"]
    assert {"tech_id", "name", "skills", "home_zone"} <= doc["technicians"]


def test_supplied_schema_has_no_differences_after_start(started: Settings):
    run_startup(started)  # a second start re-runs the migrations
    assert diff_count(started.SCHEDULING_DB_PATH) == 0


def test_app_migrations_leave_the_supplied_file_alone(started: Settings):
    conn = sqlite3.connect(f"file:{started.SCHEDULING_DB_PATH}?mode=ro", uri=True)
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert not tables & APP_TABLES
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    conn.close()
