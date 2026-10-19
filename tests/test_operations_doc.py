"""S40: docs/OPERATIONS.md names the operator commands that really exist."""

import importlib
import re

from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings
from tests.conftest import REPO
from tests.test_scheduling_reset import SEED_COUNTS

DOC = REPO / "docs" / "OPERATIONS.md"
COMMANDS = {
    "python -m app.scheduling.reset": "app.scheduling.reset",
    "python -m app.knowledge.rebuild": "app.knowledge.rebuild",
}
ROUTES = ("/admin/reset-scheduling", "/admin/rebuild-index")


def test_documented_commands_are_real_modules():
    text = DOC.read_text()
    for command, module in COMMANDS.items():
        print(command, "->", module)
        assert command in text
        assert callable(importlib.import_module(module).main)


def test_documented_routes_are_post_routes(started: Settings):
    text = DOC.read_text()
    client = TestClient(create_app(started))
    for path in ROUTES:
        status = client.post(path).status_code
        print(
            "POST", path, "documented:", path in text, "status without token:", status
        )
        assert path in text
        assert status == 401


def test_doc_uses_only_the_token_variable():
    bearers = set(re.findall(r"Bearer ([^\s\"']+)", DOC.read_text()))
    print("bearer values:", bearers)
    assert bearers == {"$ADMIN_TOKEN"}


def test_doc_slot_counts_match_the_seed():
    text = DOC.read_text()
    found = {
        name: int(match.group(1))
        for name in SEED_COUNTS
        if (match := re.search(rf'"{name}": ?(\d+)', text))
    }
    print("doc slot counts:", found)
    assert found == SEED_COUNTS
