from datetime import datetime, timezone, timedelta
from uuid import UUID, uuid4

import pytest
from playwright.sync_api import expect
from sqlalchemy import func, select

from app.audit.models import AuditLog
from app.auth.models import AuthSession
from app.detection.models import AlertRecord
from app.incidents.models import Incident
from app.investigations import service
from app.investigations.models import Investigation, Observation
from app.users.models import User
from test_investigations import investigation_context
from test_logs import log_context
from test_web import ORIGIN, browser_login, server_login, web_page


@pytest.fixture
def web_context(investigation_context):
    client, factory, _, analyst, _, password, _ = investigation_context
    with factory() as db: encoded = db.get(User, analyst).password_hash
    return client, factory, password, encoded


def open_entry(web_context, web_page):
    page = web_page[0]
    browser_login(page, web_context[2], "log-analyst")
    page.get_by_role("link", name="Investigations", exact=True).click()
    expect(page.locator("#investigation-panel")).to_be_visible()
    return page


def create_investigation(web_context, web_page, investigation_context):
    page = open_entry(web_context, web_page)
    page.get_by_label("Alert NEW (UUID)", exact=True).fill(str(investigation_context[2]))
    page.get_by_role("button", name="Iniciar investigação", exact=True).click()
    expect(page.locator('[data-investigation-field="status"]')).to_have_text("IN_REVIEW")
    return page, UUID(page.url.rsplit("/", 1)[1])


@pytest.mark.parametrize("path", ["/app/investigations", f"/app/investigations/{uuid4()}"])
@pytest.mark.parametrize("actor,expected", [("analyst", 200), ("admin", 403), ("anonymous", 303)])
def test_pages_authorize_on_server(web_context, path, actor, expected):
    # Arrange
    client, _, password, _ = web_context
    if actor == "admin": server_login(client, password, "log-admin")
    elif actor == "anonymous": client.cookies.clear()
    # Act
    response = client.get(path, follow_redirects=False)
    # Assert
    assert response.status_code == expected and response.headers["cache-control"] == "no-store"
    if expected != 200: assert 'id="investigation-panel"' not in response.text


def test_creation_and_lookup_use_real_identifier(web_context, web_page, investigation_context):
    # Arrange
    page, identifier = create_investigation(web_context, web_page, investigation_context)
    # Act
    page.goto(ORIGIN + "/app/investigations")
    page.get_by_label("Investigation (UUID)", exact=True).fill(str(identifier))
    page.get_by_role("button", name="Consultar investigação", exact=True).click()
    # Assert
    expect(page.locator('[data-investigation-field="id"]')).to_have_text(str(identifier))
    with web_context[1]() as db:
        assert db.get(Investigation, identifier).alert_id == investigation_context[2]
        assert db.get(AlertRecord, investigation_context[2]).status == "IN_REVIEW"
    assert not any(method == "GET" and url == ORIGIN + "/investigations" for method, url, _ in web_page[2])


def test_invalid_and_missing_ids(web_context, web_page):
    # Arrange
    page = open_entry(web_context, web_page)
    page.get_by_label("Alert NEW (UUID)", exact=True).fill("invalid")
    # Act
    page.get_by_role("button", name="Iniciar investigação", exact=True).click()
    sent = any(method == "POST" and url == ORIGIN + "/investigations" for method, url, _ in web_page[2])
    page.get_by_label("Alert NEW (UUID)", exact=True).fill(str(uuid4()))
    page.get_by_role("button", name="Iniciar investigação", exact=True).click()
    expect(page.locator("#feedback")).to_have_text("Registro não encontrado.")
    page.goto(ORIGIN + f"/app/investigations/{uuid4()}")
    # Assert
    assert not sent
    expect(page.locator("#feedback")).to_have_text("Registro não encontrado.")
    expect(page.locator("#investigation-data")).to_be_hidden()


def test_observations_pagination_and_xss(web_context, web_page, investigation_context, tmp_path):
    # Arrange
    page, identifier = create_investigation(web_context, web_page, investigation_context)
    with web_context[1].begin() as db:
        for n in range(12): db.add(Observation(investigation_id=identifier, analyst_id=investigation_context[3], content=f"existing-{n}", occurred_at=datetime.now(timezone.utc)))
    malicious = '<img src=x onerror="window.injected=true">'
    # Act
    page.get_by_label("Observação", exact=True).fill(malicious)
    page.get_by_role("button", name="Registrar observação", exact=True).click()
    expect(page.locator("#feedback")).to_contain_text("Observação registrada")
    page.get_by_label("Por página", exact=True).select_option("10")
    expect(page.locator("#observation-results tr")).to_have_count(10)
    page.get_by_role("button", name="Próxima", exact=True).click()
    # Assert
    expect(page.locator("#page-summary")).to_have_text("Página 2 · 13 registro(s)")
    expect(page.locator("#observation-results")).to_contain_text(malicious)
    assert page.locator("#observation-results img").count() == 0 and page.evaluate("window.injected === undefined")
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.screenshot(path=str(tmp_path / "investigation-mobile.png"), full_page=True)


@pytest.mark.parametrize("decision", ["dismiss", "escalate"])
def test_decisions_and_incident_navigation(web_context, web_page, investigation_context, decision):
    # Arrange
    page, identifier = create_investigation(web_context, web_page, investigation_context)
    # Act
    if decision == "dismiss":
        page.get_by_role("button", name="Descartar False Positive", exact=True).click()
        page.get_by_label("Justificativa", exact=True).fill("  Atividade legítima\n")
        page.get_by_role("button", name="Confirmar descarte", exact=True).click()
    else: page.get_by_role("button", name="Escalonar para Incident", exact=True).click()
    # Assert
    expect(page.locator('[data-investigation-field="status"]')).to_have_text("DISMISSED" if decision == "dismiss" else "ESCALATED")
    expect(page.locator("#investigation-decisions")).to_be_hidden()
    with web_context[1]() as db:
        assert db.scalar(select(func.count()).select_from(Incident)) == (0 if decision == "dismiss" else 1)
        assert db.scalar(select(func.count()).select_from(AuditLog)) == 1
        if decision == "dismiss": assert db.get(Investigation, identifier).justification == "  Atividade legítima\n"
        else: incident_id = db.scalar(select(Incident.id))
    if decision == "escalate":
        page.get_by_role("link", name="Abrir Incident", exact=True).click()
        expect(page.locator('[data-incident-field="id"]')).to_have_text(str(incident_id))
        expect(page.locator('[data-incident-field="severity"]')).to_have_text("HIGH")


def test_empty_text_and_duplicate_write_are_blocked(web_context, web_page, investigation_context):
    # Arrange
    page, _ = create_investigation(web_context, web_page, investigation_context)
    page.get_by_label("Observação", exact=True).fill(" \n")
    # Act
    page.get_by_role("button", name="Registrar observação", exact=True).click()
    expect(page.locator("#feedback")).to_contain_text("não vazia")
    pending = []
    page.route("**/investigations/*/escalate", lambda route: pending.append(route))
    page.get_by_role("button", name="Escalonar para Incident", exact=True).click()
    expect(page.get_by_role("button", name="Sair", exact=True)).to_be_disabled()
    page.locator("#escalate-investigation").evaluate("button => button.dispatchEvent(new MouseEvent('click'))")
    count = len(pending); pending[0].fallback()
    # Assert
    assert count == 1
    expect(page.locator('[data-investigation-field="status"]')).to_have_text("ESCALATED")


def test_conflict_reloads_current_state(web_context, web_page, investigation_context):
    # Arrange
    page, identifier = create_investigation(web_context, web_page, investigation_context)
    def conflict(route):
        with web_context[1].begin() as db: service.dismiss(db, investigation_context[3], identifier, "Concurrent decision")
        route.fulfill(status=409, json={"detail": "private-value"})
    page.route("**/investigations/*/escalate", conflict)
    # Act
    page.get_by_role("button", name="Escalonar para Incident", exact=True).click()
    # Assert
    expect(page.locator("#feedback")).to_contain_text("Conflito: estado atualizado")
    expect(page.locator('[data-investigation-field="status"]')).to_have_text("DISMISSED")
    assert "private-value" not in page.content()
    expect(page.locator("#investigation-decisions")).to_be_hidden()


@pytest.mark.parametrize("failure", ["csrf", "expired", "http"])
def test_security_and_http_failures(web_context, web_page, investigation_context, failure):
    # Arrange
    page, _ = create_investigation(web_context, web_page, investigation_context)
    if failure == "expired":
        with web_context[1].begin() as db:
            for session in db.scalars(select(AuthSession)):
                session.created_at = datetime.now(timezone.utc)-timedelta(hours=2)
                session.expires_at = datetime.now(timezone.utc)-timedelta(hours=1)
    def intercept(route):
        if failure == "http": route.fulfill(status=503, json={"detail": "private-value"})
        else:
            headers=route.request.all_headers();headers.pop("x-csrf-token",None);route.fallback(headers=headers)
    if failure != "expired": page.route("**/investigations/*/escalate", intercept)
    # Act
    page.get_by_role("button", name="Escalonar para Incident", exact=True).click()
    # Assert
    if failure == "expired": page.wait_for_url(ORIGIN+"/login?reason=session")
    elif failure == "csrf":
        expect(page.locator("#feedback")).to_contain_text("Acesso negado")
        expect(page.locator("#investigation-panel")).to_be_hidden()
    else:
        expect(page.locator("#feedback")).to_contain_text("Atualize antes de repetir")
        expect(page.locator("#investigation-decisions")).to_be_hidden()
        assert "private-value" not in page.content()
    assert page.evaluate("localStorage.length + sessionStorage.length") == 0
