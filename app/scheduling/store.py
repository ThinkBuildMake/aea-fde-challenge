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


class SchedulingUnavailable(Exception):
    """The supplied scheduling database could not be used."""


def connect(ctx: AppContext) -> sqlite3.Connection:
    """The temporary copy of the supplied database; callers must close it.

    A missing file raises before connecting: sqlite3 would create an empty one,
    and startup never reseeds an existing file.
    """
    path = ctx.settings.SCHEDULING_DB_PATH
    if not path.is_file():
        raise SchedulingUnavailable("scheduling database unavailable")
    return connect_scheduling_db(path)


def zone_for_city(city: str) -> Zone | None:
    return ZONE_BY_CITY.get(city)
