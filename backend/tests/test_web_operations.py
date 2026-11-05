from uuid import UUID

import pytest
from playwright.sync_api import expect
from sqlalchemy import select

from app.assets.models import Asset
from app.audit.models import AuditLog
from app.detection.models import DetectionRuleRecord
from test_detection_persistence import record
from test_investigations import login
from test_logs import log_context
from test_web import ORIGIN, browser_login, web_page


@pytest.fixture
def web_context(log_context):
    client, factory, _, _, _, password, _ = log_context
    return client, factory, password, None


def test_admin_manages_assets_and_rules_through_existing_api(log_context, web_page):
    # Arrange
    _, factory, _, _, _, password, _ = log_context
    page, _, requests = web_page
    browser_login(page, password, "log-admin")
    page.get_by_role("link", name="Assets e regras", exact=True).click()
    # Act
    page.get_by_label("Nome", exact=True).fill("<img src=x onerror=alert(1)>")
    page.get_by_role("button", name="Cadastrar Asset", exact=True).click()
    expect(page.locator("#operation-result")).to_contain_text("ACTIVE")
    identifier = UUID(page.locator("#operation-result").inner_text().split()[1])
    page.get_by_role("link", name="Atualizar Assets e regras", exact=True).click()
    asset = page.locator("[data-asset-row]").filter(has_text=str(identifier))
    asset.get_by_label("Nome do Asset", exact=True).fill("Asset sintético atualizado")
    asset.get_by_label("Tipo do Asset", exact=True).select_option("APPLICATION")
    asset.get_by_role("button", name="Salvar Asset", exact=True).click()
    expect(asset.get_by_role("heading")).to_have_text("Asset sintético atualizado")
    page.once("dialog", lambda dialog: dialog.accept())
    asset.get_by_role("button", name="Desativar Asset", exact=True).click()
    expect(asset.locator("[data-record-status]")).to_have_text("INACTIVE")
    page.get_by_label("Estado DR01", exact=True).select_option("INACTIVE")
    page.get_by_role("button", name="Salvar DR01", exact=True).click()
    # Assert
    expect(page.locator("#operation-result")).to_have_text("Registro DR01 · INACTIVE")
    expect(asset.get_by_role("button", name="Desativar Asset", exact=True)).to_be_disabled()
    assert asset.locator("img").count() == 0
    with factory() as db:
        saved = db.get(Asset, identifier)
        assert (saved.name, saved.type, saved.status) == ("Asset sintético atualizado", "APPLICATION", "INACTIVE")
        assert db.get(DetectionRuleRecord, "DR01").status == "INACTIVE"
        actions = set(db.scalars(select(AuditLog.action)))
    assert actions == {"ASSET_CREATED", "ASSET_UPDATED", "ASSET_DEACTIVATED", "DETECTION_RULE_DEACTIVATED"}
    writes = [headers for method, url, headers in requests if method in {"POST", "PATCH"}
              and any(part in url for part in ("/assets", "/detection-rules"))]
    assert len(writes) == 4
    assert all(headers["origin"] == ORIGIN and len(headers["x-csrf-token"]) == 64 for headers in writes)


@pytest.mark.parametrize("actor", ["log-admin", "log-analyst"])
def test_logs_page_filters_and_preserves_safe_text(log_context, web_page, actor):
    # Arrange
    client, _, asset, _, _, password, _ = log_context
    username = "<img src=x onerror=alert(1)>"
    response = client.post("/logs/import", json=[
        record(asset, 0, 0, username=username), record(asset, 1, 1, username="outro"),
    ])
    assert response.json()["accepted"] == 2
    page, _, _ = web_page
    page.set_viewport_size({"width": 390, "height": 850})
    browser_login(page, password, actor)
    # Act
    page.get_by_role("link", name="Consultar Logs", exact=True).click()
    page.goto(ORIGIN + "/app/logs?page_size=1")
    page.get_by_role("link", name="Próxima", exact=True).click()
    expect(page.get_by_role("navigation", name="Páginas de Logs")).to_contain_text("Página 2")
    expect(page.locator("#log-results")).to_contain_text(username)
    page.get_by_label("Asset (UUID)", exact=True).fill(str(asset))
    page.get_by_label("Conta monitorada", exact=True).fill(username)
    page.get_by_label("Tipo de evento", exact=True).select_option("AUTH_FAILURE")
    page.get_by_role("button", name="Aplicar filtros", exact=True).click()
    # Assert
    expect(page.locator("#log-results tr")).to_have_count(1)
    expect(page.locator("#log-results")).to_contain_text(username)
    assert page.locator("#log-results img").count() == 0
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_operations_role_and_invalid_log_filter(log_context):
    # Arrange
    client, _, _, _, _, password, _ = log_context
    login(client, "log-analyst", password)
    # Act
    denied = client.get("/app/operacoes")
    invalid = client.get("/app/logs", params={"asset_id": "entrada-privada-invalida"})
    # Assert
    assert denied.status_code == 403 and 'id="operations-panel"' not in denied.text
    assert invalid.status_code == 422 and "Filtros inválidos" in invalid.text
    assert "entrada-privada-invalida" not in invalid.text
    assert denied.headers["cache-control"] == invalid.headers["cache-control"] == "no-store"
