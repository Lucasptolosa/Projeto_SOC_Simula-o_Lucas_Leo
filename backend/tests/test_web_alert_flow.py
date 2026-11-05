from uuid import UUID, uuid4

import pytest
from playwright.sync_api import expect
from sqlalchemy import func, select

from app.detection.models import AlertRecord
from app.incidents.models import Incident
from app.investigations.models import Investigation
from test_detection_persistence import record
from test_detection_transactions import committed_detection_db
from test_soc_flow import flow
from test_web import ORIGIN, browser_login, web_page


@pytest.fixture
def web_context(flow):
    client, session, _, _, _, password, _ = flow
    return client, session, password, None


def import_alerts(flow, usernames):
    client, _, _, asset, *_ = flow
    records = [record(asset, account * 5 + n, n, username=username)
               for account, username in enumerate(usernames) for n in range(5)]
    result = client.post("/logs/import", json=records)
    assert result.status_code == 200
    assert result.json()["detection"]["alerts_created"] == len(usernames)


def test_alert_pages_deny_admin_and_anonymous(flow):
    # Arrange
    client = flow[0]
    paths = ("/app/alerts", f"/app/alerts/{uuid4()}")
    # Act
    admin = [client.get(path, follow_redirects=False) for path in paths]
    client.cookies.clear()
    anonymous = [client.get(path, follow_redirects=False) for path in paths]
    # Assert
    assert [response.status_code for response in admin + anonymous] == [403, 403, 303, 303]
    assert all('id="alerts-panel"' not in response.text for response in admin + anonymous)


@pytest.mark.parametrize("resolve", [False, True])
def test_browser_flow_recovers_links_and_updates_dashboard(flow, web_page, resolve):
    # Arrange
    username = '<img src=x onerror="window.injected=true">'
    import_alerts(flow, [username])
    with flow[1]() as db:
        alert = str(db.scalar(select(AlertRecord.id)))
    page, _, requests = web_page
    page.set_viewport_size({"width": 1280 if resolve else 390, "height": 850})
    browser_login(page, flow[5], "flow-analyst")
    # Act
    page.get_by_role("link", name="Dashboard", exact=True).click()
    expect(page.locator("#alert-status").get_by_role("row", name="NEW 1")).to_be_visible()
    page.get_by_role("link", name="Consultar Alerts", exact=True).click()
    page.get_by_role("link", name=alert, exact=True).click()
    expect(page.locator("#alert-evidence tr")).to_have_count(5)
    expect(page.locator("#alert-evidence")).to_contain_text(username)
    page.get_by_role("link", name="Iniciar Investigation", exact=True).click()
    expect(page.get_by_label("Alert NEW (UUID)")).to_have_value(alert)
    page.get_by_role("button", name="Iniciar investigação", exact=True).click()
    status = page.locator('[data-investigation-field="status"]')
    expect(status).to_have_text("IN_REVIEW")
    investigation_path = page.url
    page.get_by_label("Observação", exact=True).fill("Evidência verificada")
    page.get_by_role("button", name="Registrar observação", exact=True).click()
    expect(page.locator("#observation-results")).to_contain_text("Evidência verificada")
    if resolve:
        page.get_by_role("button", name="Escalonar para Incident", exact=True).click()
        expect(status).to_have_text("ESCALATED")
        page.reload()
        page.get_by_role("link", name="Abrir Incident", exact=True).click()
        incident_status = page.locator('[data-incident-field="status"]')
        expect(incident_status).to_have_text("OPEN")
        page.get_by_role("button", name="Iniciar tratamento", exact=True).click()
        expect(incident_status).to_have_text("UNDER_INVESTIGATION")
        page.get_by_role("button", name="Registrar contenção", exact=True).click()
        page.get_by_label("Descrição da contenção", exact=True).fill("Ativo isolado")
        page.get_by_role("button", name="Confirmar", exact=True).click()
        expect(incident_status).to_have_text("CONTAINED")
        page.get_by_role("button", name="Resolver", exact=True).click()
        page.get_by_label("Conclusão da resolução", exact=True).fill("Correção confirmada")
        page.get_by_role("button", name="Confirmar", exact=True).click()
        expect(incident_status).to_have_text("RESOLVED")
    else:
        page.get_by_role("button", name="Descartar False Positive", exact=True).click()
        page.get_by_label("Justificativa", exact=True).fill("Atividade legítima")
        page.get_by_role("button", name="Confirmar descarte", exact=True).click()
        expect(status).to_have_text("DISMISSED")
    page.get_by_role("link", name="Dashboard", exact=True).click()
    # Assert
    state = "ESCALATED" if resolve else "DISMISSED"
    expect(page.locator("#alert-status").get_by_role("row", name=f"{state} 1")).to_be_visible()
    expect(page.locator("#incident-status").get_by_role("row", name=f"RESOLVED {int(resolve)}")).to_be_visible()
    page.get_by_role("button", name="Sair", exact=True).click()
    page.wait_for_url(ORIGIN + "/login?reason=logout")
    browser_login(page, flow[5], "flow-analyst")
    page.goto(f"{ORIGIN}/app/alerts/{alert}")
    expect(page.get_by_role("link", name="Abrir Investigation", exact=True)).to_be_visible()
    assert page.get_by_role("link", name="Iniciar Investigation", exact=True).count() == 0
    assert page.get_by_role("link", name="Abrir Incident", exact=True).count() == int(resolve)
    assert page.locator("#alert-evidence img").count() == 0
    assert not page.evaluate("Boolean(window.injected)")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.get_by_role("link", name="Abrir Investigation", exact=True).click()
    expect(page).to_have_url(investigation_path)
    expect(status).to_have_text(state)
    with flow[1]() as db:
        assert db.scalar(select(func.count()).select_from(Incident)) == int(resolve)
        assert db.scalar(select(Investigation.alert_id)) == UUID(alert)
    writes = [headers for method, url, headers in requests if method == "POST" and "/investigations" in url]
    assert len(writes) == 3
    assert all(headers["origin"] == ORIGIN and len(headers["x-csrf-token"]) == 64 for headers in writes)


def test_alert_filters_pagination_and_retry_use_api(flow, web_page):
    # Arrange
    import_alerts(flow, [f"monitored-{n}" for n in range(11)])
    page, _, requests = web_page
    browser_login(page, flow[5], "flow-analyst")
    page.get_by_role("link", name="Alerts", exact=True).click()
    expect(page.locator("#page-summary")).to_have_text("Página 1 · 11 registro(s)")
    # Act
    page.get_by_label("Severity", exact=True).select_option("HIGH")
    page.get_by_label("Status", exact=True).select_option("NEW")
    page.get_by_label("Detection Rule", exact=True).select_option("DR01")
    page.get_by_label("Asset (UUID)", exact=True).fill(str(flow[3]))
    page.get_by_label("Criação inicial (horário local)", exact=True).fill("2026-01-01T00:00")
    page.get_by_role("button", name="Aplicar filtros", exact=True).click()
    expect(page.locator("#page-summary")).to_have_text("Página 1 · 11 registro(s)")
    page.get_by_label("Por página", exact=True).select_option("10")
    expect(page.locator("#alerts-results tr")).to_have_count(10)
    page.route("**/alerts?*", lambda route: route.fulfill(status=503), times=1)
    page.get_by_role("button", name="Próxima", exact=True).click()
    expect(page.locator("#feedback")).to_contain_text("Não foi possível consultar Alerts")
    page.get_by_role("button", name="Tentar novamente", exact=True).click()
    # Assert
    expect(page.locator("#page-summary")).to_have_text("Página 2 · 11 registro(s)")
    expect(page.locator("#alerts-results tr")).to_have_count(1)
    assert any(method == "GET" and all(part in url for part in (
        "severity=HIGH", "status=NEW", "rule_id=DR01", f"asset_id={flow[3]}", "created_from=", "page=2", "page_size=10",
    )) for method, url, _ in requests)
    assert not any(method == "POST" and "/alerts" in url for method, url, _ in requests)
