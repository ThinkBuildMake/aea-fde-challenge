"""Start-up work: seed copy (only if missing) and app-database migrations."""

import json
import os
import shutil
import sys
from pathlib import Path

from app.db import apply_migrations, connect_app_db, latest_migration_version
from app.settings import Settings

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def run_startup(settings: Settings) -> None:
    for path in (
        settings.SCHEDULING_DB_PATH,
        settings.APP_DB_PATH,
        settings.INDEX_PATH,
    ):
        path.parent.mkdir(parents=True, exist_ok=True)

    seeded = False
    target = settings.SCHEDULING_DB_PATH
    if not target.exists():
        temp = target.with_name(target.name + ".seeding")
        shutil.copyfile(settings.SEED_DB_PATH, temp)
        os.replace(temp, target)
        seeded = True

    conn = connect_app_db(settings.APP_DB_PATH)
    try:
        apply_migrations(conn, MIGRATIONS_DIR)
    finally:
        conn.close()

    event = {
        "event": "startup",
        "seeded": seeded,
        "schema_version": latest_migration_version(MIGRATIONS_DIR),
    }
    sys.stdout.write(json.dumps(event) + "\n")
    sys.stdout.flush()
