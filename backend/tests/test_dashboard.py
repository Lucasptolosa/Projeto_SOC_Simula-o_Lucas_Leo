from uuid import UUID

import pytest
from playwright.sync_api import expect

from test_alert_queries import alerts_context
from test_incident_queries import incident_queries, snapshot
from test_investigations import login
from test_logs import log_context
from test_web import browser_login, web_page
from test_web_incidents import web_context


@pytest.mark.parametrize("actor,api_status,page_status", [("admin", 403, 403), ("anonymous", 401, 303)])
def test_dashboard_enforces_server_role(log_context, actor, api_status, page_status):
    # Arrange
    client, _, _, _, _, password, _ = log_context
    if actor == "admin":
        login(client, "log-admin", password)
    else:
        client.cookies.clear()
    # Act
    api = client.get("/dashboard")
    page = client.get("/app/dashboard", follow_redirects=False)
    # Assert
    assert (api.status_code, page.status_code) == (api_status, page_status)
    assert api.headers["cache-control"] == page.headers["cache-control"] == "no-store"
    assert 'id="alert-status"' not in page.text


def test_empty_dashboard_exposes_all_zero_categories(log_context):
    # Arrange
    client, _, _, _, _, password, _ = log_context
    login(client, "log-analyst", password)
    # Act
    response = client.get("/dashboard")
    # Assert
    severity = dict.fromkeys(("LOW", "MEDIUM", "HIGH", "CRITICAL"), 0)
    assert response.status_code == 200
    assert response.json() == {
        "alerts": {"severity": severity, "status": dict.fromkeys(("NEW", "IN_REVIEW", "DISMISSED", "ESCALATED"), 0)},
        "incidents": {"severity": severity, "status": dict.fromkeys(("OPEN", "UNDER_INVESTIGATION", "CONTAINED", "RESOLVED"), 0)},
    }


def test_alert_counts_use_persisted_statuses_without_writes(alerts_context):
    # Arrange
    client, factory, *_ = alerts_context
    before = snapshot(factory)
    # Act
    response = client.get("/dashboard")
    # Assert
    assert response.status_code == 200
    assert response.json()["alerts"] == {
        "severity": {"LOW": 1, "MEDIUM": 1, "HIGH": 5, "CRITICAL": 1},
        "status": {"NEW": 5, "IN_REVIEW": 1, "DISMISSED": 1, "ESCALATED": 1},
    }
    assert snapshot(factory) == before


def test_incident_transition_updates_only_relevant_bucket(incident_queries):
    # Arrange
    client, *_ = incident_queries
    before = client.get("/dashboard").json()
    # Act
    transition = client.post(f"/incidents/{UUID(int=2)}/transitions", json={"target_status": "UNDER_INVESTIGATION"})
    after = client.get("/dashboard").json()
    # Assert
    assert transition.status_code == 200
    assert before["incidents"]["status"] == dict.fromkeys(("OPEN", "UNDER_INVESTIGATION", "CONTAINED", "RESOLVED"), 3)
    assert after["incidents"]["status"] == {"OPEN": 2, "UNDER_INVESTIGATION": 4, "CONTAINED": 3, "RESOLVED": 3}
    assert before["incidents"]["severity"] == after["incidents"]["severity"] == dict.fromkeys(("LOW", "MEDIUM", "HIGH", "CRITICAL"), 3)
    assert before["alerts"] == after["alerts"]


@pytest.mark.parametrize("width", [360, 1280])
def test_dashboard_renders_readable_counts_in_chromium(web_context, web_page, width):
    # Arrange
    page, _, _ = web_page
    page.set_viewport_size({"width": width, "height": 900})
    browser_login(page, web_context[2], "log-analyst")
    # Act
    page.get_by_role("link", name="Dashboard", exact=True).click()
    # Assert
    expect(page.get_by_role("heading", name="Dashboard de segurança")).to_be_visible()
    expect(page.locator("#alert-status").get_by_role("row", name="ESCALATED 12")).to_be_visible()
    expect(page.locator("#incident-status").get_by_role("row", name="RESOLVED 3")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
