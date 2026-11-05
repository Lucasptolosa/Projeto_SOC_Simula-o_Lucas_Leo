from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import pytest
from playwright.sync_api import expect
from sqlalchemy import func, select

from app.audit.models import AuditLog
from app.auth.models import AuthSession
from app.incidents import service
from app.incidents.models import Incident
from app.incidents.schemas import TransitionInput
from app.users.models import User
from test_incident_queries import START, PRIORITY_IDS, incident_queries, snapshot
from test_logs import log_context
from test_web import ORIGIN, browser_login, server_login, web_page


@pytest.fixture
def web_context(incident_queries):
    client, factory, _, analyst, password, _ = incident_queries
    with factory() as db:
        encoded = db.get(User, analyst).password_hash
    return client, factory, password, encoded


def open_incidents(web_context, web_page, identifier=None):
    page, _, _ = web_page
    browser_login(page, web_context[2], "log-analyst")
    page.goto(ORIGIN + "/app/incidents" + (f"/{identifier}" if identifier else ""))
    expect(page.locator("#incident-panel")).to_be_visible()
    if identifier:
        expect(page.locator('[data-incident-field="id"]')).to_have_text(str(identifier))
    else:
        expect(page.locator("#page-summary")).to_have_text("Página 1 · 12 registro(s)")
    return page


@pytest.mark.parametrize("path", ["/app/incidents", f"/app/incidents/{UUID(int=2)}"])
@pytest.mark.parametrize("condition,expected", [("analyst", 200), ("admin", 403), ("anonymous", 303), ("inactive", 303), ("expired", 303)])
def test_incident_pages_authorize_on_server(web_context, incident_queries, path, condition, expected):
    # Arrange
    client, factory, password, _ = web_context
    analyst = incident_queries[3]
    if condition == "admin":
        server_login(client, password, "log-admin")
    elif condition == "anonymous":
        client.cookies.clear()
    elif condition == "inactive":
        with factory.begin() as db:
            db.get(User, analyst).status = "INACTIVE"
    elif condition == "expired":
        with factory.begin() as db:
            for session in db.scalars(select(AuthSession)):
                session.created_at = datetime.now(timezone.utc) - timedelta(hours=2)
                session.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    # Act
    response = client.get(path, follow_redirects=False)
    # Assert
    assert response.status_code == expected and response.headers["cache-control"] == "no-store"
    assert "'unsafe-inline'" not in response.headers["content-security-policy"]
    if expected == 303:
        assert response.headers["location"] == "/login?reason=session"
    if expected != 200:
        assert 'id="incident-panel"' not in response.text


def test_analyst_navigation_priority_and_read_only_pages(web_context, web_page, tmp_path):
    # Arrange
    page, _, requests = web_page
    browser_login(page, web_context[2], "log-analyst")
    before = snapshot(web_context[1])
    # Act
    page.get_by_role("link", name="Incidents", exact=True).click()
    expect(page.locator("#incident-results tr")).to_have_count(12)
    ordered = page.locator("#incident-results tr td:first-child").all_text_contents()
    page.screenshot(path=str(tmp_path / "incidents-desktop.png"), full_page=True)
    page.get_by_role("link", name=f"Abrir detalhes do Incident {UUID(int=2)}", exact=True).click()
    # Assert
    assert ordered == [str(UUID(int=number)) for number in PRIORITY_IDS]
    expect(page.locator('[data-incident-field="status"]')).to_have_text("OPEN")
    expect(page.locator('[data-incident-field="severity"]')).to_have_text("CRITICAL")
    assert page.get_by_role("link", name="Usuários", exact=True).count() == 0
    assert not any("/users?" in url or "/audit-logs?" in url for _, url, _ in requests)
    assert snapshot(web_context[1]) == before


def test_admin_home_preserves_navigation(web_context, web_page):
    # Arrange
    page, _, _ = web_page
    # Act
    browser_login(page, web_context[2], "log-admin")
    # Assert
    expect(page.get_by_role("link", name="Usuários", exact=True)).to_be_visible()
    expect(page.get_by_role("link", name="Auditoria", exact=True)).to_be_visible()
    assert page.get_by_role("link", name="Incidents", exact=True).count() == 0


def test_invalid_filters_do_not_query(web_context, web_page):
    # Arrange
    page = open_incidents(web_context, web_page)
    before = len([url for _, url, _ in web_page[2] if "/incidents?" in url])
    page.get_by_label("Abertura inicial (horário local)").fill("2026-11-07T10:00")
    page.get_by_label("Abertura final (horário local)").fill("2026-11-06T10:00")
    # Act
    page.get_by_role("button", name="Aplicar filtros", exact=True).click()
    expect(page.locator("#feedback")).to_contain_text("início não pode ser posterior")
    page.get_by_label("Asset (UUID)", exact=True).fill("invalid")
    page.get_by_role("button", name="Aplicar filtros", exact=True).click()
    # Assert
    assert not page.locator("#incident-filters").evaluate("form => form.checkValidity()")
    assert len([url for _, url, _ in web_page[2] if "/incidents?" in url]) == before


def test_combined_filters_dates_and_empty_state(web_context, web_page, incident_queries):
    # Arrange
    page = open_incidents(web_context, web_page)
    page.get_by_label("Status", exact=True).select_option("UNDER_INVESTIGATION")
    page.get_by_label("Severity", exact=True).select_option("HIGH")
    page.get_by_label("Asset (UUID)", exact=True).fill(str(incident_queries[2][1]))
    local = page.evaluate("""value => {
        const d = new Date(value), p = n => String(n).padStart(2, '0');
        return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
    }""", START.isoformat())
    page.get_by_label("Abertura inicial (horário local)").fill(local)
    page.get_by_label("Abertura final (horário local)").fill(local)
    # Act
    page.get_by_role("button", name="Aplicar filtros", exact=True).click()
    expect(page.locator("#page-summary")).to_have_text("Página 1 · 1 registro(s)")
    identifier = page.locator("#incident-results tr td:first-child").inner_text()
    query = next(parse_qs(urlsplit(url).query) for method, url, _ in reversed(web_page[2]) if method == "GET" and "/incidents?" in url)
    page.get_by_label("Asset (UUID)", exact=True).fill(str(uuid4()))
    page.get_by_role("button", name="Aplicar filtros", exact=True).click()
    # Assert
    assert identifier == str(UUID(int=5))
    assert query["status"] == ["UNDER_INVESTIGATION"] and query["severity"] == ["HIGH"]
    assert datetime.fromisoformat(query["opened_from"][0]) == datetime.fromisoformat(query["opened_to"][0]) == START
    assert query["opened_from"][0].endswith("Z")
    expect(page.locator("#incident-results")).to_have_text("Nenhum Incident encontrado.")
    expect(page.locator("#next-page")).to_be_disabled()


def test_pagination_uses_api_and_keeps_order(web_context, web_page):
    # Arrange
    page = open_incidents(web_context, web_page)
    # Act
    page.get_by_label("Por página", exact=True).select_option("10")
    expect(page.locator("#incident-results tr")).to_have_count(10)
    first = page.locator("#incident-results tr td:first-child").all_text_contents()
    page.get_by_role("button", name="Próxima", exact=True).click()
    expect(page.locator("#page-summary")).to_have_text("Página 2 · 12 registro(s)")
    second = page.locator("#incident-results tr td:first-child").all_text_contents()
    # Assert
    assert first + second == [str(UUID(int=number)) for number in PRIORITY_IDS]
    expect(page.locator("#next-page")).to_be_disabled()
    page.get_by_role("button", name="Anterior", exact=True).click()
    expect(page.locator("#page-summary")).to_have_text("Página 1 · 12 registro(s)")
    assert any("page=2" in url and "page_size=10" in url for _, url, _ in web_page[2])


@pytest.mark.parametrize("contained", [False, True])
def test_treatment_lifecycle_and_history(web_context, web_page, contained):
    # Arrange
    page = open_incidents(web_context, web_page, UUID(int=2))
    with web_context[1]() as db:
        original = db.get(Incident, UUID(int=2))
        opener, opened_at = original.analyst_id, original.opened_at
        audit_count = db.scalar(select(func.count()).select_from(AuditLog))
    # Act
    page.get_by_role("button", name="Iniciar tratamento", exact=True).click()
    expect(page.locator('[data-incident-field="status"]')).to_have_text("UNDER_INVESTIGATION")
    if contained:
        page.get_by_role("button", name="Registrar contenção", exact=True).click()
        page.get_by_label("Descrição da contenção", exact=True).fill("  Isolamento realizado\n")
        page.get_by_role("button", name="Confirmar", exact=True).click()
        expect(page.locator('[data-incident-field="status"]')).to_have_text("CONTAINED")
    page.get_by_role("button", name="Resolver" if contained else "Resolver diretamente", exact=True).click()
    page.get_by_label("Conclusão da resolução", exact=True).fill("  Correção confirmada\n")
    page.get_by_role("button", name="Confirmar", exact=True).click()
    # Assert
    expect(page.locator('[data-incident-field="status"]')).to_have_text("RESOLVED")
    expect(page.locator("#feedback")).to_contain_text("Novo Status: RESOLVED")
    assert page.locator("#incident-actions button").count() == 0
    assert page.locator('[data-incident-field="resolution_conclusion"]').text_content() == "  Correção confirmada\n"
    if contained:
        assert page.locator('[data-incident-field="containment_description"]').text_content() == "  Isolamento realizado\n"
    with web_context[1]() as db:
        row = db.get(Incident, UUID(int=2))
        assert row.analyst_id == opener and row.opened_at == opened_at and row.resolved_by == opener
        assert row.contained_by == (opener if contained else None)
        assert db.scalar(select(func.count()).select_from(AuditLog)) == audit_count + (3 if contained else 2)
    writes = [headers for method, url, headers in web_page[2] if method == "POST" and "/transitions" in url]
    assert len(writes) == (3 if contained else 2)
    assert all(headers["origin"] == ORIGIN and len(headers["x-csrf-token"]) == 64 for headers in writes)
    assert page.evaluate("localStorage.length + sessionStorage.length") == 0


@pytest.mark.parametrize("status,identifier,labels", [
    ("OPEN", 2, ["Iniciar tratamento"]),
    ("UNDER_INVESTIGATION", 5, ["Registrar contenção", "Resolver diretamente"]),
    ("CONTAINED", 3, ["Resolver"]), ("RESOLVED", 9, []),
])
def test_only_current_actions_and_aware_dates(web_context, web_page, status, identifier, labels):
    # Arrange
    page = open_incidents(web_context, web_page, UUID(int=identifier))
    # Act
    buttons = page.locator("#incident-actions button").all_text_contents()
    opening = page.locator('[data-incident-field="opened_at"]')
    # Assert
    assert buttons == labels
    assert datetime.fromisoformat(opening.inner_text()).tzinfo is not None
    assert opening.get_attribute("datetime") == opening.inner_text()
    expect(page.locator('[data-incident-field="status"]')).to_have_text(status)


def test_invalid_text_and_cancel_do_not_write(web_context, web_page):
    # Arrange
    page = open_incidents(web_context, web_page, UUID(int=5))
    page.get_by_role("button", name="Registrar contenção", exact=True).click()
    # Act
    page.get_by_role("button", name="Confirmar", exact=True).click()
    valid = page.locator("#incident-transition-form").evaluate("form => form.checkValidity()")
    page.get_by_label("Descrição da contenção", exact=True).fill("  \n")
    page.get_by_role("button", name="Confirmar", exact=True).click()
    expect(page.locator("#incident-form-error")).to_contain_text("texto obrigatório")
    page.get_by_role("button", name="Cancelar", exact=True).click()
    # Assert
    assert not valid and not any("/transitions" in url for _, url, _ in web_page[2])
    expect(page.locator("#incident-dialog")).not_to_be_visible()
    expect(page.locator("#incident-text")).to_have_value("")


def test_duplicate_submission_is_blocked(web_context, web_page):
    # Arrange
    page = open_incidents(web_context, web_page, UUID(int=2))
    pending = []
    page.route("**/incidents/*/transitions", lambda route: pending.append(route))
    # Act
    page.get_by_role("button", name="Iniciar tratamento", exact=True).click()
    expect(page.get_by_role("button", name="Iniciar tratamento", exact=True)).to_be_disabled()
    expect(page.get_by_role("button", name="Sair", exact=True)).to_be_disabled()
    page.locator("#incident-actions button").evaluate("button => {button.dispatchEvent(new MouseEvent('click')); button.dispatchEvent(new MouseEvent('click'));}")
    count = len(pending)
    pending[0].fallback()
    # Assert
    assert count == 1
    expect(page.locator('[data-incident-field="status"]')).to_have_text("UNDER_INVESTIGATION")
    expect(page.get_by_role("button", name="Sair", exact=True)).to_be_enabled()


@pytest.mark.parametrize("refresh_failure", [False, True])
def test_conflict_requires_current_state_before_new_decision(web_context, web_page, refresh_failure):
    # Arrange
    page = open_incidents(web_context, web_page, UUID(int=5))
    def conflict(route):
        with web_context[1].begin() as db:
            author = db.get(Incident, UUID(int=5)).analyst_id
            service.transition(db, author, UUID(int=5), TransitionInput(target_status="RESOLVED", resolution_conclusion="Concurrent decision"))
        if refresh_failure:
            page.route(f"**/incidents/{UUID(int=5)}", lambda query: query.fulfill(status=503))
        route.fulfill(status=409, json={"detail": "private-server-value"})
    page.route("**/incidents/*/transitions", conflict)
    # Act
    page.get_by_role("button", name="Resolver diretamente", exact=True).click()
    page.get_by_label("Conclusão da resolução", exact=True).fill("Local decision")
    page.get_by_role("button", name="Confirmar", exact=True).click()
    expect(page.locator("#feedback")).to_contain_text("Conflito")
    # Assert
    assert page.locator("#incident-actions button").count() == 0
    assert "private-server-value" not in page.content()
    if refresh_failure:
        expect(page.locator("#incident-data")).to_be_hidden()
        page.unroute(f"**/incidents/{UUID(int=5)}")
        page.get_by_role("button", name="Tentar novamente", exact=True).click()
    expect(page.locator('[data-incident-field="status"]')).to_have_text("RESOLVED")
    expect(page.locator('[data-incident-field="resolution_conclusion"]')).to_have_text("Concurrent decision")


@pytest.mark.parametrize("error", [422, 503, "network"])
def test_write_failure_has_safe_feedback_and_recovery(web_context, web_page, error):
    # Arrange
    page = open_incidents(web_context, web_page, UUID(int=5))
    def fail(route):
        route.abort() if error == "network" else route.fulfill(status=error, json={"detail": "private-server-value"})
    page.route("**/incidents/*/transitions", fail)
    page.get_by_role("button", name="Registrar contenção", exact=True).click()
    page.get_by_label("Descrição da contenção", exact=True).fill("containment")
    # Act
    page.get_by_role("button", name="Confirmar", exact=True).click()
    # Assert
    if error == 422:
        expect(page.locator("#incident-form-error")).to_contain_text("Dados inválidos")
        expect(page.get_by_role("button", name="Confirmar", exact=True)).to_be_enabled()
    else:
        expect(page.locator("#feedback")).to_contain_text("Atualize o detalhe antes de repetir")
        assert page.locator("#incident-actions button").count() == 0
        page.get_by_role("button", name="Tentar novamente", exact=True).click()
        expect(page.get_by_role("button", name="Registrar contenção", exact=True)).to_be_enabled()
    assert "private-server-value" not in page.content()
    with web_context[1]() as db:
        assert db.get(Incident, UUID(int=5)).status.value == "UNDER_INVESTIGATION"


@pytest.mark.parametrize("target", ["list", "detail"])
def test_query_failures_and_retry(web_context, web_page, target):
    # Arrange
    page, _, _ = web_page
    browser_login(page, web_context[2], "log-analyst")
    pattern = ORIGIN + "/incidents?*" if target == "list" else ORIGIN + f"/incidents/{UUID(int=2)}"
    page.route(pattern, lambda route: route.fulfill(status=503, json={"detail": "private-server-value"}))
    # Act
    page.goto(ORIGIN + "/app/incidents" + (f"/{UUID(int=2)}" if target == "detail" else ""))
    expect(page.locator("#feedback")).to_contain_text("Não foi possível acessar o servidor")
    page.unroute(pattern)
    page.get_by_role("button", name="Tentar novamente", exact=True).click()
    # Assert
    expect(page.locator("#incident-panel")).to_be_visible()
    if target == "list":
        expect(page.locator("#incident-results tr")).to_have_count(12)
    else:
        expect(page.locator('[data-incident-field="status"]')).to_have_text("OPEN")
    assert "private-server-value" not in page.content()


def test_missing_incident_is_reported(web_context, web_page):
    # Arrange
    page, _, _ = web_page
    browser_login(page, web_context[2], "log-analyst")
    # Act
    page.goto(ORIGIN + f"/app/incidents/{uuid4()}")
    # Assert
    expect(page.locator("#feedback")).to_have_text("Incident não encontrado.")
    expect(page.locator("#incident-data")).to_be_hidden()
    assert page.locator("#incident-actions button").count() == 0


@pytest.mark.parametrize("condition", ["expired", "inactive", "role"])
def test_live_session_or_permission_change_blocks_area(web_context, web_page, incident_queries, condition):
    # Arrange
    page = open_incidents(web_context, web_page)
    with web_context[1].begin() as db:
        author = db.get(User, incident_queries[3])
        if condition == "role":
            author.role = "ADMIN"
        elif condition == "inactive":
            author.status = "INACTIVE"
        else:
            for session in db.scalars(select(AuthSession)):
                session.created_at = datetime.now(timezone.utc) - timedelta(hours=2)
                session.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    # Act
    page.get_by_role("button", name="Aplicar filtros", exact=True).click()
    # Assert
    if condition == "role":
        expect(page.locator("#feedback")).to_contain_text("Acesso negado")
        expect(page.locator("#incident-panel")).to_be_hidden()
        expect(page.get_by_role("link", name="Incidents", exact=True)).to_be_hidden()
    else:
        page.wait_for_url(ORIGIN + "/login?reason=session")


def test_csrf_failure_reloads_identity_and_blocks_actions(web_context, web_page):
    # Arrange
    page = open_incidents(web_context, web_page, UUID(int=2))
    def tamper(route):
        headers = route.request.all_headers()
        headers.pop("x-csrf-token")
        route.fallback(headers=headers)
    page.route("**/incidents/*/transitions", tamper)
    # Act
    page.get_by_role("button", name="Iniciar tratamento", exact=True).click()
    # Assert
    expect(page.locator("#feedback")).to_contain_text("Acesso negado")
    expect(page.locator("#incident-panel")).to_be_hidden()
    with web_context[1]() as db:
        assert db.get(Incident, UUID(int=2)).status.value == "OPEN"


def test_xss_responsiveness_and_private_data(web_context, web_page, tmp_path):
    # Arrange
    malicious = '<img src=x onerror="window.injected=true">'
    with web_context[1].begin() as db:
        row = db.get(Incident, UUID(int=9))
        row.resolution_conclusion = malicious
    page, _, _ = web_page
    page.set_viewport_size({"width": 390, "height": 844})
    # Act
    open_incidents(web_context, web_page, UUID(int=9))
    # Assert
    expect(page.locator('[data-incident-field="resolution_conclusion"]')).to_have_text(malicious)
    assert page.locator("#incident-resolution img").count() == 0 and page.evaluate("window.injected === undefined")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert page.evaluate("localStorage.length + sessionStorage.length") == 0
    assert web_context[2] not in page.content() and web_context[3] not in page.content()
    page.screenshot(path=str(tmp_path / "incident-mobile.png"), full_page=True)
