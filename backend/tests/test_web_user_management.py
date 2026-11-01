import secrets
from datetime import datetime, timedelta, timezone

import pytest
from playwright.sync_api import expect
from sqlalchemy import select

from app.audit.models import AuditLog
from app.auth.models import AuthSession
from app.auth.service import COOKIE_NAME
from app.core.passwords import verify_password
from app.users.models import User, UserRole, UserStatus
from test_web import ADMIN, ANALYST, ORIGIN, browser_login, web_context, web_page


def open_users(web_context, web_page):
    _, _, password, _ = web_context
    page, _, _ = web_page
    browser_login(page, password)
    page.goto(ORIGIN + "/app/users")
    expect(page.locator("#results tr")).to_have_count(20)
    return page


def open_create(page, username, password, role="ANALYST", confirmation=None):
    page.get_by_role("button", name="Novo usuário", exact=True).click()
    page.get_by_label("Username", exact=True).fill(username)
    page.get_by_label("Papel da conta", exact=True).select_option(role)
    page.get_by_label("Senha do novo usuário", exact=True).fill(password)
    page.get_by_label("Confirmar senha", exact=True).fill(password if confirmation is None else confirmation)


def audit_ids(factory):
    with factory() as db:
        return set(db.scalars(select(AuditLog.id)))


@pytest.mark.parametrize("role", ["ADMIN", "ANALYST"])
def test_cadastro_visual_persiste_e_audita(web_context, web_page, role, caplog):
    # Arrange
    _, factory, _, _ = web_context
    page = open_users(web_context, web_page)
    password = secrets.token_urlsafe(24)
    before = audit_ids(factory)
    payload_keys = []

    def inspect_create(route):
        payload_keys.append(set(route.request.post_data_json))
        route.fallback()

    page.route(ORIGIN + "/users", inspect_create)
    open_create(page, "nova-conta", password, role)

    # Act
    page.get_by_role("button", name="Criar usuário", exact=True).click()
    expect(page.locator("#operation-result")).to_have_text("Usuário cadastrado com sucesso.")
    expect(page.locator("#results")).to_contain_text("nova-conta")

    # Assert
    expect(page.locator("#user-dialog")).not_to_be_visible()
    assert page.locator("#user-password").input_value() == ""
    assert page.locator("#user-password-confirmation").input_value() == ""
    assert password not in page.content() + caplog.text
    assert page.evaluate("localStorage.length + sessionStorage.length") == 0
    with factory() as db:
        account = db.scalar(select(User).where(User.username == "nova-conta"))
        assert account.role.value == role and account.status is UserStatus.ACTIVE
        password_valid = verify_password(password, account.password_hash)
        assert password_valid
        events = list(db.scalars(select(AuditLog).where(AuditLog.id.not_in(before))))
        assert len(events) == 1
        assert events[0].action == "USER_CREATED" and events[0].author_id == ADMIN
        assert events[0].entity_id == str(account.id)
        assert account.password_hash not in page.content() + caplog.text
    writes = [(method, url, headers) for method, url, headers in web_page[2] if method in {"POST", "PATCH"} and "/users" in url]
    assert len(writes) == 1
    assert writes[0][2]["origin"] == ORIGIN and len(writes[0][2]["x-csrf-token"]) == 64
    assert writes[0][2]["content-type"] == "application/json"
    assert password not in writes[0][1]
    assert payload_keys == [{"username", "role", "password"}]


def test_cadastro_senhas_divergentes_nao_envia(web_context, web_page):
    # Arrange
    page = open_users(web_context, web_page)
    open_create(page, "nao-criar", secrets.token_urlsafe(24), confirmation=secrets.token_urlsafe(24))

    # Act
    page.get_by_role("button", name="Criar usuário", exact=True).click()

    # Assert
    expect(page.locator("#user-error")).to_contain_text("As senhas não coincidem")
    expect(page.get_by_label("Senha do novo usuário", exact=True)).to_have_value("")
    expect(page.get_by_label("Confirmar senha", exact=True)).to_have_value("")
    assert not any(method == "POST" and url == ORIGIN + "/users" for method, url, _ in web_page[2])


@pytest.mark.parametrize("field", ["username", "password"])
def test_cadastro_campos_brancos_nao_envia(web_context, web_page, field):
    # Arrange
    page = open_users(web_context, web_page)
    open_create(page, "   " if field == "username" else "nova-conta", "   " if field == "password" else secrets.token_urlsafe(24))

    # Act
    page.get_by_role("button", name="Criar usuário", exact=True).click()

    # Assert
    expect(page.locator("#user-error")).to_contain_text("campos obrigatórios")
    assert not any(method == "POST" and url == ORIGIN + "/users" for method, url, _ in web_page[2])


def test_cadastro_obrigatorios_e_cancelamento_limpa_senhas(web_context, web_page):
    # Arrange
    page = open_users(web_context, web_page)
    page.get_by_role("button", name="Novo usuário", exact=True).click()

    # Act
    page.get_by_role("button", name="Criar usuário", exact=True).click()
    valid = page.locator("#user-form").evaluate("form => form.checkValidity()")
    password = secrets.token_urlsafe(24)
    page.get_by_label("Senha do novo usuário", exact=True).fill(password)
    page.get_by_label("Confirmar senha", exact=True).fill(password)
    page.locator("#user-dialog").get_by_role("button", name="Cancelar", exact=True).click()

    # Assert
    assert not valid
    expect(page.locator("#user-dialog")).not_to_be_visible()
    assert page.locator("#user-password").input_value() == ""
    assert page.locator("#user-password-confirmation").input_value() == ""
    assert not any(method == "POST" and url == ORIGIN + "/users" for method, url, _ in web_page[2])


def test_username_duplicado_tratado_pelo_servidor(web_context, web_page):
    # Arrange
    _, factory, _, _ = web_context
    page = open_users(web_context, web_page)
    before = audit_ids(factory)
    open_create(page, "analista", secrets.token_urlsafe(24))

    # Act
    page.get_by_role("button", name="Criar usuário", exact=True).click()

    # Assert
    expect(page.locator("#user-error")).to_contain_text("Username já cadastrado")
    expect(page.get_by_label("Senha do novo usuário", exact=True)).to_have_value("")
    assert audit_ids(factory) == before


@pytest.mark.parametrize("name,role", [("analista-renomeado", "ANALYST"), ("analista", "ADMIN"), ("analista-renomeado", "ADMIN")])
def test_edicao_preserva_uuid_hash_e_auditoria_unica(web_context, web_page, name, role):
    # Arrange
    _, factory, _, encoded = web_context
    page = open_users(web_context, web_page)
    before = audit_ids(factory)
    payload_keys = []

    def inspect_patch(route):
        payload_keys.append(set(route.request.post_data_json))
        route.fallback()

    page.route(f"**/users/{ANALYST}", inspect_patch)
    page.get_by_role("button", name="Editar analista", exact=True).click()
    page.get_by_label("Username", exact=True).fill(name)
    page.get_by_label("Papel da conta", exact=True).select_option(role)

    # Act
    page.get_by_role("button", name="Salvar alterações", exact=True).click()
    expect(page.locator("#operation-result")).to_have_text("Usuário atualizado com sucesso.")
    expect(page.locator("#results")).to_contain_text(name)

    # Assert
    assert payload_keys == [{"username", "role"}]
    with factory() as db:
        account = db.get(User, ANALYST)
        assert account.username == name and account.role.value == role
        assert account.password_hash == encoded and account.status is UserStatus.ACTIVE
        events = list(db.scalars(select(AuditLog).where(AuditLog.id.not_in(before))))
        assert len(events) == 1 and events[0].action == "USER_UPDATED"
        assert events[0].entity_id == str(ANALYST) and events[0].author_id == ADMIN
        assert events[0].old_role == (UserRole.ANALYST if role == "ADMIN" else None)
        assert events[0].new_role == (UserRole.ADMIN if role == "ADMIN" else None)
        assert set(db.scalars(select(AuditLog.id))) >= before
    writes = [headers for method, url, headers in web_page[2] if method == "PATCH"]
    assert len(writes) == 1 and len(writes[0]["x-csrf-token"]) == 64
    assert writes[0]["origin"] == ORIGIN


def test_edicao_propria_indisponivel_e_protegida_no_servidor(web_context, web_page):
    # Arrange
    _, factory, _, _ = web_context
    page = open_users(web_context, web_page)

    # Act
    response = page.evaluate("""async id => {
        const me = await (await fetch('/auth/me', {credentials: 'same-origin'})).json();
        return (await fetch('/users/' + id, {method: 'PATCH', credentials: 'same-origin',
            headers: {'Content-Type': 'application/json', 'X-CSRF-Token': me.csrf_token},
            body: JSON.stringify({role: 'ANALYST'})})).status;
    }""", str(ADMIN))

    # Assert
    expect(page.get_by_role("button", name="Editar administrador", exact=True)).to_be_disabled()
    expect(page.get_by_text("Sua conta · edição indisponível")).to_be_visible()
    assert response == 403
    with factory() as db:
        assert db.get(User, ADMIN).role is UserRole.ADMIN


def test_ultimo_admin_preservado_pela_api(web_context, web_page):
    # Arrange
    _, factory, _, _ = web_context
    page = open_users(web_context, web_page)
    before = audit_ids(factory)
    page.get_by_role("button", name="Desativar administrador", exact=True).click()

    # Act
    page.get_by_role("button", name="Confirmar desativação", exact=True).click()

    # Assert
    expect(page.locator("#deactivate-error")).to_contain_text("O último ADMIN ativo deve ser preservado")
    assert audit_ids(factory) == before
    with factory() as db:
        assert db.get(User, ADMIN).status is UserStatus.ACTIVE


def test_desativacao_cancelada_nao_envia_e_foco_seguro(web_context, web_page):
    # Arrange
    _, factory, _, _ = web_context
    page = open_users(web_context, web_page)
    before = audit_ids(factory)

    # Act
    page.get_by_role("button", name="Desativar analista", exact=True).click()
    warning = page.locator("#deactivate-warning").inner_text()
    cancel_focused = page.locator("#deactivate-dialog .dialog-cancel").evaluate("button => button === document.activeElement")
    page.locator("#deactivate-dialog").get_by_role("button", name="Cancelar", exact=True).click()

    # Assert
    assert "perderá acesso" in warning and "sessões serão revogadas" in warning
    assert cancel_focused
    expect(page.locator("#deactivate-dialog")).not_to_be_visible()
    assert not any(url.endswith("/deactivate") for _, url, _ in web_page[2])
    assert audit_ids(factory) == before


def test_desativacao_revoga_sessoes_e_mostra_auditoria(web_context, web_page):
    # Arrange
    client, factory, password, _ = web_context
    client.post("/auth/login", json={"username": "analista", "password": password}, headers={"Origin": ORIGIN})
    previous_token = client.cookies.get(COOKIE_NAME)
    page = open_users(web_context, web_page)
    before = audit_ids(factory)
    page.get_by_role("button", name="Desativar analista", exact=True).click()

    # Act
    page.get_by_role("button", name="Confirmar desativação", exact=True).click()
    expect(page.locator("#operation-result")).to_contain_text("Usuário desativado")
    expect(page.get_by_role("button", name="Desativar analista", exact=True)).to_be_disabled()
    client.cookies.clear()
    access = client.get("/auth/me", headers={"Cookie": f"{COOKIE_NAME}={previous_token}"})
    page.get_by_role("link", name="Consultar histórico de auditoria", exact=True).click()

    # Assert
    assert access.status_code == 401
    expect(page.locator("#results")).to_contain_text("Usuário desativado")
    with factory() as db:
        assert db.get(User, ANALYST).status is UserStatus.INACTIVE
        sessions = list(db.scalars(select(AuthSession).where(AuthSession.user_id == ANALYST)))
        assert sessions and all(session.revoked_at is not None for session in sessions)
        events = list(db.scalars(select(AuditLog).where(AuditLog.id.not_in(before))))
        assert len(events) == 1 and events[0].action == "USER_DEACTIVATED"
    writes = [(method, url, headers) for method, url, headers in web_page[2] if url.endswith("/deactivate")]
    assert len(writes) == 1 and len(writes[0][2]["x-csrf-token"]) == 64
    assert writes[0][2]["origin"] == ORIGIN


def test_desativacao_de_dado_desatualizado_trata_409(web_context, web_page):
    # Arrange
    _, factory, _, _ = web_context
    page = open_users(web_context, web_page)
    with factory.begin() as db:
        db.get(User, ANALYST).status = UserStatus.INACTIVE
    page.get_by_role("button", name="Desativar analista", exact=True).click()

    # Act
    page.get_by_role("button", name="Confirmar desativação", exact=True).click()

    # Assert
    expect(page.locator("#deactivate-error")).to_contain_text("Usuário já está inativo")


def test_analyst_sem_formularios_ou_acoes(web_context, web_page):
    # Arrange
    _, _, password, _ = web_context
    page, _, _ = web_page
    browser_login(page, password, "analista")

    # Act
    page.goto(ORIGIN + "/app/users")

    # Assert
    expect(page.get_by_role("heading", name="Permissão insuficiente")).to_be_visible()
    assert page.locator("#create-user, #user-form, #deactivate-form").count() == 0


@pytest.mark.parametrize("operation", ["create", "update", "deactivate"])
def test_todas_mutacoes_exigem_csrf(web_context, web_page, operation):
    # Arrange
    _, factory, _, _ = web_context
    page = open_users(web_context, web_page)
    before = audit_ids(factory)
    url = ORIGIN + ("/users" if operation == "create" else f"/users/{ANALYST}" + ("/deactivate" if operation == "deactivate" else ""))

    def remove_csrf(route):
        headers = route.request.all_headers()
        headers.pop("x-csrf-token", None)
        route.fallback(headers=headers)

    page.route(url, remove_csrf)
    if operation == "create":
        open_create(page, "nova-conta", secrets.token_urlsafe(24))
        button = page.get_by_role("button", name="Criar usuário", exact=True)
    elif operation == "update":
        page.get_by_role("button", name="Editar analista", exact=True).click()
        page.get_by_label("Username", exact=True).fill("outro-nome")
        button = page.get_by_role("button", name="Salvar alterações", exact=True)
    else:
        page.get_by_role("button", name="Desativar analista", exact=True).click()
        button = page.get_by_role("button", name="Confirmar desativação", exact=True)

    # Act
    button.click()

    # Assert
    expect(page.locator("#feedback")).to_contain_text("Acesso negado")
    assert audit_ids(factory) == before


@pytest.mark.parametrize("status", [401, 403, 409, 422, 500])
def test_erros_mutacao_sem_refletir_detalhes(web_context, web_page, status):
    # Arrange
    page = open_users(web_context, web_page)
    password = secrets.token_urlsafe(24)
    page.route(ORIGIN + "/users", lambda route: route.fulfill(status=status, json={"detail": "SEGREDO <img src=x>"}))
    open_create(page, "nova-conta", password)

    # Act
    page.get_by_role("button", name="Criar usuário", exact=True).click()

    # Assert
    if status == 401:
        page.wait_for_url(ORIGIN + "/login?reason=session")
        assert "query-panel" not in page.content()
    elif status == 403:
        expect(page.locator("#feedback")).to_contain_text("Acesso negado")
        expect(page.locator("#user-dialog")).not_to_be_visible()
    else:
        expect(page.locator("#user-error")).not_to_be_empty()
        expect(page.get_by_label("Senha do novo usuário", exact=True)).to_have_value("")
    assert "SEGREDO" not in page.content() and password not in page.content()


def test_sessao_expirada_durante_formulario(web_context, web_page):
    # Arrange
    _, factory, _, _ = web_context
    page = open_users(web_context, web_page)
    open_create(page, "nova-conta", secrets.token_urlsafe(24))
    before = audit_ids(factory)
    with factory.begin() as db:
        session = db.scalar(select(AuthSession))
        session.created_at = datetime.now(timezone.utc) - timedelta(hours=2)
        session.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)

    # Act
    page.get_by_role("button", name="Criar usuário", exact=True).click()

    # Assert
    page.wait_for_url(ORIGIN + "/login?reason=session")
    assert page.locator("#user-form").count() == 0
    assert audit_ids(factory) == before


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844)])
def test_dialogos_teclado_layout_e_xss(web_context, web_page, width, height):
    # Arrange
    _, factory, _, _ = web_context
    malicious = '<img src=x onerror="window.injected=true">'
    with factory.begin() as db:
        db.get(User, ANALYST).username = malicious
    page, _, _ = web_page
    page.set_viewport_size({"width": width, "height": height})
    open_users(web_context, web_page)

    # Act
    page.get_by_role("button", name="Editar " + malicious, exact=True).click()
    username_value = page.get_by_label("Username", exact=True).input_value()
    page.get_by_label("Username", exact=True).press("Escape")
    page.get_by_role("button", name="Desativar " + malicious, exact=True).click()

    # Assert
    expect(page.locator("#deactivate-username")).to_have_text(malicious)
    assert username_value == malicious
    assert page.locator("#results img, #deactivate-dialog img").count() == 0
    assert page.evaluate("window.injected === undefined")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    bounds = page.locator("#deactivate-dialog").bounding_box()
    assert bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= width
    assert bounds["y"] >= 0 and bounds["y"] + bounds["height"] <= height


def test_envio_duplicado_bloqueado_durante_requisicao(web_context, web_page):
    # Arrange
    _, factory, _, _ = web_context
    page = open_users(web_context, web_page)
    pending = []
    page.route(ORIGIN + "/users", lambda route: pending.append(route))
    open_create(page, "nova-conta", secrets.token_urlsafe(24))

    # Act
    page.get_by_role("button", name="Criar usuário", exact=True).click()
    expect(page.get_by_role("button", name="Criar usuário", exact=True)).to_be_disabled()
    page.locator("#user-form").dispatch_event("submit")
    page.get_by_label("Username", exact=True).press("Escape")
    open_while_pending = page.locator("#user-dialog").is_visible()
    requests_while_pending = len(pending)
    pending[0].fallback()

    # Assert
    assert requests_while_pending == 1 and open_while_pending
    expect(page.locator("#operation-result")).to_have_text("Usuário cadastrado com sucesso.")
    with factory() as db:
        assert len(list(db.scalars(select(User).where(User.username == "nova-conta")))) == 1


def test_papel_revogado_com_formulario_aberto(web_context, web_page):
    # Arrange
    _, factory, _, _ = web_context
    page = open_users(web_context, web_page)
    open_create(page, "nova-conta", secrets.token_urlsafe(24))
    before = audit_ids(factory)
    with factory.begin() as db:
        db.get(User, ADMIN).role = UserRole.ANALYST

    # Act
    page.get_by_role("button", name="Criar usuário", exact=True).click()

    # Assert
    expect(page.locator("#feedback")).to_contain_text("Acesso negado")
    expect(page.locator("#query-panel")).to_be_hidden()
    expect(page.locator("#user-dialog")).not_to_be_visible()
    expect(page.locator("#current-role")).to_have_text("ANALYST")
    assert page.locator("#user-password").input_value() == ""
    assert audit_ids(factory) == before


def test_falha_rede_nao_repete_mutacao(web_context, web_page):
    # Arrange
    _, factory, _, _ = web_context
    page = open_users(web_context, web_page)
    attempts = []

    def unavailable(route):
        attempts.append(route.request.method)
        route.abort()

    page.route(ORIGIN + "/users", unavailable)
    open_create(page, "nova-conta", secrets.token_urlsafe(24))
    before = audit_ids(factory)

    # Act
    page.get_by_role("button", name="Criar usuário", exact=True).click()

    # Assert
    expect(page.locator("#user-error")).to_contain_text("atualize a listagem antes de repetir")
    expect(page.get_by_role("button", name="Criar usuário", exact=True)).to_be_enabled()
    assert attempts == ["POST"]
    assert page.locator("#user-password").input_value() == ""
    assert audit_ids(factory) == before


def test_criacao_atualiza_listagem_preservando_filtros(web_context, web_page):
    # Arrange
    page = open_users(web_context, web_page)
    page.get_by_label("Papel", exact=True).select_option("ANALYST")
    page.get_by_label("Estado", exact=True).select_option("ACTIVE")
    page.get_by_role("button", name="Aplicar filtros", exact=True).click()
    expect(page.locator("#page-summary")).to_have_text("Página 1 · 22 registro(s)")
    page.get_by_role("button", name="Próxima", exact=True).click()
    expect(page.locator("#page-summary")).to_have_text("Página 2 · 22 registro(s)")
    open_create(page, "nova-conta", secrets.token_urlsafe(24))

    # Act
    page.get_by_role("button", name="Criar usuário", exact=True).click()

    # Assert
    expect(page.locator("#page-summary")).to_have_text("Página 1 · 23 registro(s)")
    expect(page.locator("#results")).to_contain_text("nova-conta")
    expect(page.get_by_label("Papel", exact=True)).to_have_value("ANALYST")
    expect(page.get_by_label("Estado", exact=True)).to_have_value("ACTIVE")


def test_autodesativacao_com_outro_admin_conduz_login(web_context, web_page):
    # Arrange
    _, factory, _, encoded = web_context
    with factory.begin() as db:
        db.add(User(username="outro-admin", role="ADMIN", password_hash=encoded))
    page = open_users(web_context, web_page)
    page.get_by_role("button", name="Desativar administrador", exact=True).click()

    # Act
    page.get_by_role("button", name="Confirmar desativação", exact=True).click()

    # Assert
    page.wait_for_url(ORIGIN + "/login?reason=session")
    assert page.locator("#user-form, #results").count() == 0
    with factory() as db:
        assert db.get(User, ADMIN).status is UserStatus.INACTIVE
        assert all(item.revoked_at is not None for item in db.scalars(select(AuthSession).where(AuthSession.user_id == ADMIN)))


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844)])
def test_cadastro_por_teclado_e_layout(web_context, web_page, tmp_path, width, height):
    # Arrange
    page, _, _ = web_page
    page.set_viewport_size({"width": width, "height": height})
    open_users(web_context, web_page)
    page.screenshot(path=tmp_path / "usuarios.png", full_page=True)

    # Act
    page.get_by_role("button", name="Novo usuário", exact=True).focus()
    page.get_by_role("button", name="Novo usuário", exact=True).press("Enter")
    focused_on_username = page.get_by_label("Username", exact=True).evaluate("input => input === document.activeElement")
    page.screenshot(path=tmp_path / "cadastro.png", full_page=True)
    page.get_by_label("Username", exact=True).press("Tab")
    focused_on_role = page.get_by_label("Papel da conta", exact=True).evaluate("input => input === document.activeElement")
    bounds = page.locator("#user-dialog").bounding_box()
    page.get_by_label("Papel da conta", exact=True).press("Escape")

    # Assert
    assert focused_on_username and focused_on_role
    expect(page.locator("#user-dialog")).not_to_be_visible()
    expect(page.get_by_role("button", name="Novo usuário", exact=True)).to_be_focused()
    assert bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= width
    assert bounds["y"] >= 0 and bounds["y"] + bounds["height"] <= height
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
