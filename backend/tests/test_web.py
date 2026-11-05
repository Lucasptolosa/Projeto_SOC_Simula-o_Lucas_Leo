import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import expect
from sqlalchemy import select

from app.audit.models import AuditLog
from app.auth.dependencies import get_auth_settings
from app.auth.models import AuthSession
from app.auth.service import COOKIE_NAME
from app.core.passwords import hash_password
from app.db.session import get_session
from app.main import app
from app.users.models import User, UserRole, UserStatus


ORIGIN = "https://testserver"
ADMIN = UUID(int=100)
ANALYST = UUID(int=200)


@pytest.fixture
def web_context(users_db, test_db_settings, request):
    factory, connection = users_db
    password = secrets.token_urlsafe(24)
    encoded = hash_password(password)
    with factory.begin() as db:
        db.add_all([
            User(id=ADMIN, username="administrador", role="ADMIN", password_hash=encoded),
            User(id=ANALYST, username="analista", role="ANALYST", password_hash=encoded),
            User(username="desativado", role="ANALYST", status="INACTIVE", password_hash=encoded),
        ])
        db.add_all([User(username=f"usuario-{number:02}", role="ANALYST", password_hash=encoded) for number in range(21)])
        db.flush()
        db.add_all([AuditLog(
            id=UUID(int=1000 + number), author_id=ADMIN, action="USER_UPDATED",
            entity_type="USER", entity_id=str(ANALYST),
            occurred_at=datetime(2026, 10, 30, 12, tzinfo=timezone.utc) + timedelta(minutes=number // 2),
            old_role=UserRole.ANALYST if number == 20 else None,
            new_role=UserRole.ADMIN if number == 20 else None,
        ) for number in range(getattr(request, "param", 21))])
    settings = test_db_settings.model_copy(update={"auth_origin": ORIGIN, "auth_cookie_secure": True})
    previous = app.dependency_overrides.copy()

    def database():
        with factory() as db:
            yield db

    app.dependency_overrides[get_session] = database
    app.dependency_overrides[get_auth_settings] = lambda: settings
    try:
        with TestClient(app, base_url=ORIGIN) as client:
            yield client, factory, password, encoded
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


@pytest.fixture
def web_page(web_context, chromium):
    client, _, _, _ = web_context
    context = chromium.new_context(base_url=ORIGIN)
    requests = []

    def dispatch(route):
        request = route.request
        if not request.url.startswith(ORIGIN + "/"):
            route.abort()
            return
        # Navegador controla cookies
        client.cookies.clear()
        headers = request.all_headers()
        requests.append((request.method, request.url, headers))
        response = client.request(
            request.method, request.url, headers=headers,
            content=request.post_data_buffer, follow_redirects=False,
        )
        route.fulfill(status=response.status_code, headers=dict(response.headers), body=response.content)

    context.route("**/*", dispatch)
    page = context.new_page()
    page.set_default_timeout(10000)
    try:
        yield page, context, requests
    finally:
        context.close()


def browser_login(page, password, username="administrador"):
    page.goto(ORIGIN + "/login")
    page.get_by_label("Nome de usuário", exact=True).fill(username)
    page.get_by_label("Senha", exact=True).fill(password)
    page.get_by_role("button", name="Entrar no Mini SOC").click()
    page.wait_for_url(ORIGIN + "/app")
    expect(page.locator("#current-username")).to_have_text(username)


def server_login(client, password, username="administrador"):
    return client.post("/auth/login", json={"username": username, "password": password}, headers={"Origin": ORIGIN})


def test_pagina_login_publica_e_recursos(web_context):
    # Arrange
    client, _, _, _ = web_context

    # Act
    response = client.get("/login")
    css = client.get("/static/web.css")
    javascript = client.get("/static/web.js")
    index = client.get("/", follow_redirects=False)

    # Assert
    assert response.status_code == css.status_code == javascript.status_code == 200
    assert '<html lang="pt-BR">' in response.text
    assert 'autocomplete="current-password"' in response.text
    assert '<script src="/static/web.js" defer>' in response.text
    assert "text/css" in css.headers["content-type"]
    assert "javascript" in javascript.headers["content-type"]
    assert index.status_code == 303 and index.headers["location"] == "/app"
    assert response.headers["cache-control"] == "no-store"
    assert "'unsafe-inline'" not in response.headers["content-security-policy"]
    assert "form-action 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("path", ["/app", "/app/users", "/app/audit-logs"])
def test_pagina_anonima_nao_expoe_conteudo(web_context, path):
    # Arrange
    client, _, _, _ = web_context

    # Act
    response = client.get(path, follow_redirects=False)

    # Assert
    assert response.status_code == 303
    assert response.headers["location"] == "/login?reason=session"
    assert "query-panel" not in response.text
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("condition", ["expired", "revoked", "inactive", "invalid"])
@pytest.mark.parametrize("path", ["/app", "/app/users", "/app/audit-logs"])
def test_paginas_revalidam_sessao_e_estado(web_context, condition, path):
    # Arrange
    client, factory, password, _ = web_context
    server_login(client, password)
    with factory.begin() as db:
        session = db.scalar(select(AuthSession))
        if condition == "expired":
            session.created_at = datetime.now(timezone.utc) - timedelta(hours=2)
            session.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        elif condition == "revoked":
            session.revoked_at = datetime.now(timezone.utc)
        elif condition == "inactive":
            db.get(User, ADMIN).status = UserStatus.INACTIVE
    if condition == "invalid":
        client.cookies.clear()
        client.cookies.set(COOKIE_NAME, "invalido")

    # Act
    response = client.get(path, follow_redirects=False)

    # Assert
    assert response.status_code == 303
    assert response.headers["location"] == "/login?reason=session"
    assert "query-panel" not in response.text


@pytest.mark.parametrize("path", ["/app/users", "/app/audit-logs"])
def test_paginas_administrativas_negam_analyst(web_context, path):
    # Arrange
    client, _, password, _ = web_context
    server_login(client, password, "analista")

    # Act
    response = client.get(path)
    api = client.get("/users" if path.endswith("users") else "/audit-logs")

    # Assert
    assert response.status_code == api.status_code == 403
    assert "Permissão insuficiente" in response.text
    assert "query-panel" not in response.text
    assert "items" not in api.json()


def test_html_sem_segredos_e_contexto_minimo(web_context, caplog):
    # Arrange
    client, factory, password, encoded = web_context
    login = server_login(client, password)
    token = client.cookies.get(COOKIE_NAME)
    csrf = login.json()["csrf_token"]
    with factory() as db:
        stored_hash = db.scalar(select(AuthSession.token_hash))

    # Act
    responses = [client.get(path) for path in ["/app", "/app/users", "/app/audit-logs", "/login"]]

    # Assert
    for response in responses:
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        for secret in [password, encoded, token, csrf, stored_hash]:
            assert secret not in response.text + caplog.text
        assert "password_hash" not in response.text
        assert "csrf_token" not in response.text
    assert set(responses[0].context) == {"request", "is_admin", "page", "title"}


def test_navegador_login_logout_cookies_csrf(web_context, web_page):
    # Arrange
    _, factory, password, encoded = web_context
    page, context, requests = web_page

    # Act
    browser_login(page, password)
    cookies = context.cookies()
    html = page.content()
    storage = page.evaluate("({local: localStorage.length, session: sessionStorage.length, cookies: document.cookie})")
    page.get_by_role("button", name="Sair", exact=True).click()
    page.wait_for_url(ORIGIN + "/login?reason=logout")

    # Assert
    cookie = next(item for item in cookies if item["name"] == COOKIE_NAME)
    assert cookie["httpOnly"] and cookie["secure"] and cookie["sameSite"] == "Strict"
    assert storage == {"local": 0, "session": 0, "cookies": ""}
    assert cookie["value"] not in html and password not in html and encoded not in html
    assert not any(item["name"] == COOKIE_NAME for item in context.cookies())
    writes = [(method, url, headers) for method, url, headers in requests if method == "POST"]
    assert [url for _, url, _ in writes] == [ORIGIN + "/auth/login", ORIGIN + "/auth/logout"]
    assert all(headers["origin"] == ORIGIN for _, _, headers in writes)
    assert writes[0][2]["content-type"] == "application/json"
    assert len(writes[1][2]["x-csrf-token"]) == 64
    with factory() as db:
        assert db.scalar(select(AuthSession)).revoked_at is not None


@pytest.mark.parametrize("username", ["administrador", "inexistente", "desativado"])
def test_navegador_login_invalido_generico(web_context, web_page, username):
    # Arrange
    _, _, password, _ = web_context
    page, _, _ = web_page
    page.goto(ORIGIN + "/login")
    page.get_by_label("Nome de usuário", exact=True).fill(username)
    page.get_by_label("Senha", exact=True).fill(password if username == "desativado" else secrets.token_urlsafe(24))

    # Act
    page.get_by_role("button", name="Entrar no Mini SOC").click()

    # Assert
    expect(page.locator("#feedback")).to_have_text("Credenciais inválidas ou acesso indisponível.")
    expect(page.get_by_label("Senha", exact=True)).to_have_value("")
    assert page.url == ORIGIN + "/login"


def test_navegador_users_paginacao_filtros_e_vazio(web_context, web_page):
    # Arrange
    _, _, password, _ = web_context
    page, _, requests = web_page
    browser_login(page, password)

    # Act
    page.get_by_role("link", name="Consultar usuários").click()
    expect(page.locator("#results tr")).to_have_count(20)
    page.get_by_label("Por página").select_option("10")
    expect(page.locator("#results tr")).to_have_count(10)
    first = page.locator("#results tr").all_text_contents()
    page.get_by_role("button", name="Próxima", exact=True).click()
    expect(page.locator("#page-summary")).to_have_text("Página 2 · 24 registro(s)")
    second = page.locator("#results tr").all_text_contents()
    page.get_by_role("button", name="Anterior", exact=True).click()
    expect(page.locator("#page-summary")).to_have_text("Página 1 · 24 registro(s)")
    page.get_by_label("Papel", exact=True).select_option("ANALYST")
    page.get_by_label("Estado", exact=True).select_option("INACTIVE")
    page.get_by_role("button", name="Aplicar filtros").click()
    expect(page.locator("#results")).to_contain_text("desativado")
    expect(page.locator("#page-summary")).to_have_text("Página 1 · 1 registro(s)")
    page.get_by_label("Papel", exact=True).select_option("ADMIN")
    page.get_by_role("button", name="Aplicar filtros").click()

    # Assert
    expect(page.locator("#results")).to_have_text("Nenhum registro encontrado.")
    expect(page.locator("#next-page")).to_be_disabled()
    expect(page.locator("#previous-page")).to_be_disabled()
    assert set(first).isdisjoint(second)
    assert any("role=ANALYST&status=INACTIVE" in url for _, url, _ in requests)


def test_navegador_auditoria_ordem_dados_e_paginacao(web_context, web_page):
    # Arrange
    _, factory, password, _ = web_context
    page, _, _ = web_page
    browser_login(page, password)
    with factory() as db:
        original = list(db.scalars(select(AuditLog.id).order_by(AuditLog.id)))

    # Act
    page.get_by_role("link", name="Consultar auditoria").click()
    expect(page.locator("#results tr")).to_have_count(20)
    first = page.locator("#results tr").first.inner_text()
    page.get_by_role("button", name="Próxima", exact=True).click()
    expect(page.locator("#page-summary")).to_have_text("Página 2 · 21 registro(s)")

    # Assert
    expect(page.locator("#results tr")).to_have_count(1)
    expect(page.locator("#next-page")).to_be_disabled()
    assert str(ADMIN) in first and str(ANALYST) in first
    assert "Usuário alterado" in first and "USER" in first
    assert "ADMIN" in first and "ANALYST" in first and "09:10:00" in first
    with factory() as db:
        assert original == list(db.scalars(select(AuditLog.id).order_by(AuditLog.id)))


def test_navegador_analyst_acessa_incidents(web_context, web_page):
    # Arrange
    _, _, password, _ = web_context
    page, _, _ = web_page

    # Act
    browser_login(page, password, "analista")

    # Assert
    expect(page.locator("#current-role")).to_have_text("ANALYST")
    expect(page.get_by_role("link", name="Incidents", exact=True)).to_be_visible()
    expect(page.get_by_text("Consultar Incidents", exact=False)).to_be_visible()
    assert page.get_by_role("link", name="Usuários", exact=True).count() == 0
    assert page.get_by_role("link", name="Auditoria", exact=True).count() == 0


@pytest.mark.parametrize("condition", ["expired", "revoked", "inactive"])
def test_navegador_sessao_invalidada_durante_uso(web_context, web_page, condition):
    # Arrange
    _, factory, password, _ = web_context
    page, _, _ = web_page
    browser_login(page, password)
    page.goto(ORIGIN + "/app/users")
    expect(page.locator("#results tr")).to_have_count(20)
    with factory.begin() as db:
        session = db.scalar(select(AuthSession))
        if condition == "expired":
            session.created_at = datetime.now(timezone.utc) - timedelta(hours=2)
            session.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        elif condition == "revoked":
            session.revoked_at = datetime.now(timezone.utc)
        else:
            db.get(User, ADMIN).status = UserStatus.INACTIVE

    # Act
    page.get_by_role("button", name="Próxima", exact=True).click()

    # Assert
    page.wait_for_url(ORIGIN + "/login?reason=session")
    expect(page.locator("#feedback")).to_contain_text("Entre novamente")
    assert "query-panel" not in page.content()


@pytest.mark.parametrize("status", [403, 422, 500])
def test_navegador_erro_consulta_e_recuperacao(web_context, web_page, status):
    # Arrange
    _, _, password, _ = web_context
    page, _, _ = web_page
    browser_login(page, password)
    page.route("**/users?*", lambda route: route.fulfill(status=status, json={"detail": "Não exibir este conteúdo"}))

    # Act
    page.goto(ORIGIN + "/app/users")
    expect(page.locator("#results")).to_have_text("Consulta indisponível.")
    error_feedback = page.locator("#feedback").inner_text()
    error_html = page.content()
    page.unroute("**/users?*")
    page.get_by_role("button", name="Tentar novamente").click()

    # Assert
    assert error_feedback
    assert "Não exibir este conteúdo" not in error_html
    expect(page.locator("#results tr")).to_have_count(20)


def test_navegador_indisponibilidade_login(web_context, web_page):
    # Arrange
    _, _, password, _ = web_context
    page, _, _ = web_page
    page.goto(ORIGIN + "/login")
    page.route("**/auth/login", lambda route: route.abort())
    page.get_by_label("Nome de usuário", exact=True).fill("administrador")
    page.get_by_label("Senha", exact=True).fill(password)

    # Act
    page.get_by_role("button", name="Entrar no Mini SOC").click()

    # Assert
    expect(page.locator("#feedback")).to_contain_text("Não foi possível acessar o servidor")
    expect(page.get_by_role("button", name="Entrar no Mini SOC")).to_be_enabled()
    expect(page.get_by_label("Senha", exact=True)).to_have_value("")


def test_navegador_escape_xss_e_responsividade(web_context, web_page):
    # Arrange
    _, factory, password, _ = web_context
    malicious = '<img src=x onerror="window.injected=true">'
    with factory.begin() as db:
        db.get(User, ANALYST).username = malicious
    page, _, _ = web_page
    page.set_viewport_size({"width": 390, "height": 844})
    browser_login(page, password)

    # Act
    page.goto(ORIGIN + "/app/users")

    # Assert
    expect(page.locator("#results")).to_contain_text(malicious)
    assert page.locator("#results img").count() == 0
    assert page.evaluate("window.injected === undefined")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_navegador_logout_sem_csrf_negado(web_context, web_page):
    # Arrange
    _, factory, password, _ = web_context
    page, _, _ = web_page
    browser_login(page, password)

    # Act
    status = page.evaluate("async () => (await fetch('/auth/logout', {method: 'POST', credentials: 'same-origin'})).status")

    # Assert
    assert status == 403
    with factory() as db:
        assert db.scalar(select(AuthSession)).revoked_at is None


@pytest.mark.parametrize("web_context", [0], indirect=True)
def test_navegador_auditoria_vazia(web_context, web_page):
    # Arrange
    _, _, password, _ = web_context
    page, _, _ = web_page
    browser_login(page, password)

    # Act
    page.goto(ORIGIN + "/app/audit-logs")

    # Assert
    expect(page.locator("#results")).to_have_text("Nenhum registro encontrado.")
    expect(page.locator("#page-summary")).to_have_text("Página 1 · 0 registro(s)")
    expect(page.locator("#next-page")).to_be_disabled()
    expect(page.locator("#previous-page")).to_be_disabled()


def test_navegador_papel_atualizado_no_servidor(web_context, web_page):
    # Arrange
    _, factory, password, _ = web_context
    page, _, _ = web_page
    browser_login(page, password)
    page.goto(ORIGIN + "/app/users")
    expect(page.locator("#results tr")).to_have_count(20)
    with factory.begin() as db:
        db.get(User, ADMIN).role = UserRole.ANALYST

    # Act
    page.get_by_role("button", name="Próxima", exact=True).click()
    expect(page.locator("#results")).to_have_text("Consulta indisponível.")
    page.get_by_role("button", name="Tentar novamente").click()

    # Assert
    expect(page.locator("#feedback")).to_contain_text("Acesso negado")
    expect(page.locator("#query-panel")).to_be_hidden()
    expect(page.locator("#current-role")).to_have_text("ANALYST")
    expect(page.get_by_role("link", name="Usuários", exact=True)).to_be_hidden()


def test_navegador_erro_perfil_e_logout(web_context, web_page):
    # Arrange
    _, factory, password, _ = web_context
    page, _, _ = web_page
    browser_login(page, password)
    page.route("**/auth/me", lambda route: route.fulfill(status=503))

    # Act
    page.reload()
    expect(page.locator("#feedback")).to_contain_text("Não foi possível acessar o servidor")
    disabled_without_profile = page.get_by_role("button", name="Sair", exact=True).is_disabled()
    page.unroute("**/auth/me")
    page.get_by_role("button", name="Tentar novamente").click()
    expect(page.get_by_role("button", name="Sair", exact=True)).to_be_enabled()
    page.route("**/auth/logout", lambda route: route.fulfill(status=503))
    page.get_by_role("button", name="Sair", exact=True).click()

    # Assert
    assert disabled_without_profile
    expect(page.locator("#feedback")).to_contain_text("Não foi possível acessar o servidor")
    expect(page.get_by_role("button", name="Sair", exact=True)).to_be_enabled()
    assert page.url == ORIGIN + "/app"
    with factory() as db:
        assert db.scalar(select(AuthSession)).revoked_at is None
