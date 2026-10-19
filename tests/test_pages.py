import re

import pytest
from fastapi.testclient import TestClient

from app.llm import FakeModelProvider
from app.main import create_app
from app.settings import Settings


@pytest.fixture
def client(started: Settings) -> TestClient:
    return TestClient(create_app(started, model=FakeModelProvider()))


def test_caller_page_loads_without_sign_in(client: TestClient):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Meridian Home Comfort" in response.text
    lowered = response.text.lower()
    assert 'type="password"' not in lowered
    assert "sign in" not in lowered and "log in" not in lowered


def test_business_page_has_title_tabs_and_overview(client: TestClient):
    response = client.get("/business")
    assert response.status_code == 200
    html = response.text
    assert "Meridian AI agent: business view" in html
    tabs = re.findall(r'<a class="tab[^"]*" href="\?tab=(\w+)"[^>]*>([^<]+)</a>', html)
    assert tabs == [
        ("overview", "Overview"),
        ("handoffs", "Handoffs"),
        ("waitlist", "Waitlist"),
        ("conversations", "Conversations"),
    ]
    assert 'id="overview-body"' in html
    assert "example data" not in html.lower()


def test_overview_polls_every_30_seconds(client: TestClient):
    html = client.get("/business?tab=overview").text
    assert 'hx-trigger="every 30s"' in html
    assert 'hx-get="/business?tab=overview"' in html
    assert 'hx-select="#overview-body"' in html


@pytest.mark.parametrize("tab", ["overview", "handoffs", "waitlist", "conversations"])
def test_every_business_tab_loads(client: TestClient, tab: str):
    assert client.get(f"/business?tab={tab}").status_code == 200


def test_pages_use_only_their_own_assets(client: TestClient):
    for path in ["/", "/business"]:
        html = client.get(path).text
        assert "googleapis" not in html and "cdn" not in html.lower()
    assert client.get("/static/htmx.min.js").status_code == 200
