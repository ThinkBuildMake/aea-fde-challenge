import json
import re
import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn
from playwright.sync_api import Browser, Locator, Page, Route, sync_playwright

from app.llm import FakeModelProvider
from app.main import create_app
from app.monitoring import routes
from app.settings import Settings
from tests.test_overview_view import make_overview


@pytest.fixture(scope="session")
def browser() -> Iterator[Browser]:
    with sync_playwright() as p:
        instance = p.chromium.launch()
        yield instance
        instance.close()


@pytest.fixture
def live_url(started: Settings) -> Iterator[str]:
    app = create_app(started, model=FakeModelProvider())
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started:
        assert time.monotonic() < deadline, "server did not start"
        time.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def page(browser: Browser) -> Iterator[Page]:
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    yield context.new_page()
    context.close()


def edges(item: Locator, container: Locator) -> tuple[float, float]:
    """Gap from the container's left edge to the item's left, and from the item's
    right to the container's right."""
    a = item.bounding_box()
    b = container.bounding_box()
    assert a is not None and b is not None
    return a["x"] - b["x"], (b["x"] + b["width"]) - (a["x"] + a["width"])


@pytest.fixture
def overview_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routes, "get_overview", lambda ctx, *a, **k: make_overview())


def json_route(
    page: Page,
    pattern: re.Pattern[str],
    body: object,
    status: int = 200,
    calls: list[dict] | None = None,
) -> None:
    """Answer requests whose URL matches `pattern` with `body`, recording each call."""

    def handle(route: Route) -> None:
        req = route.request
        if calls is not None:
            calls.append(
                {
                    "method": req.method,
                    "url": req.url,
                    "body": req.post_data_json if req.post_data else None,
                }
            )
        route.fulfill(
            status=status, content_type="application/json", body=json.dumps(body)
        )

    page.route(pattern, handle)
