import sqlite3

from app.context import AppContext
from app.db import connect_scheduling_db
from app.types import Zone

ZONE_BY_CITY: dict[str, Zone] = {
    "Round Rock": "north",
    "Cedar Park": "north",
    "Pflugerville": "north",
    "Georgetown": "north",
    "Leander": "north",
    "Hutto": "north",
    "Austin": "central",
    "Kyle": "south",
    "Buda": "south",
}


def connect(ctx: AppContext) -> sqlite3.Connection:
    """The temporary copy of the supplied database; callers must close it."""
    return connect_scheduling_db(ctx.settings.SCHEDULING_DB_PATH)


def zone_for_city(city: str) -> Zone | None:
    return ZONE_BY_CITY.get(city)
