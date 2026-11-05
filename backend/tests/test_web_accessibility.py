from uuid import UUID

import pytest
from playwright.sync_api import expect

from test_incident_queries import incident_queries
from test_logs import log_context
from test_web import web_page
from test_web_incidents import open_incidents, web_context


@pytest.mark.parametrize("resolve", [False, True])
def test_keyboard_focus_survives_incident_transition(web_context, web_page, resolve):
    # Arrange
    page = open_incidents(web_context, web_page, UUID(int=2))
    start = page.get_by_role("button", name="Iniciar tratamento", exact=True)
    start.focus()
    # Act
    start.press("Enter")
    expect(page.locator('[data-incident-field="status"]')).to_have_text("UNDER_INVESTIGATION")
    if resolve:
        page.get_by_role("button", name="Resolver diretamente", exact=True).focus()
        page.keyboard.press("Enter")
        expect(page.get_by_label("Conclusão da resolução", exact=True)).to_be_focused()
        page.keyboard.type("Resolvido pelo teclado")
        page.get_by_role("button", name="Confirmar", exact=True).focus()
        page.keyboard.press("Enter")
        expect(page.locator('[data-incident-field="status"]')).to_have_text("RESOLVED")
    # Assert
    expect(page.locator('[data-incident-field="status"]')).to_be_focused()
    assert page.locator("#incident-dialog").evaluate("dialog => dialog.open") is False


@pytest.mark.parametrize("status", [409, 422, 503])
def test_transition_error_focus_has_recovery_target(web_context, web_page, status):
    # Arrange
    page = open_incidents(web_context, web_page, UUID(int=5))
    page.route("**/incidents/*/transitions", lambda route: route.fulfill(status=status, json={"detail": "failure"}))
    page.get_by_role("button", name="Resolver diretamente", exact=True).focus()
    page.keyboard.press("Enter")
    page.get_by_label("Conclusão da resolução", exact=True).fill("Verificação")
    page.get_by_role("button", name="Confirmar", exact=True).focus()
    # Act
    page.keyboard.press("Enter")
    # Assert
    if status == 422:
        expect(page.locator("#incident-form-error")).to_contain_text("Dados inválidos")
        expect(page.locator("#incident-text")).to_be_focused()
        assert page.locator("#incident-text").get_attribute("tabindex") is None
    elif status == 409:
        expect(page.locator("#feedback")).to_contain_text("Conflito")
        expect(page.locator('[data-incident-field="status"]')).to_be_focused()
    else:
        expect(page.locator("#feedback")).to_contain_text("Atualize o detalhe")
        expect(page.locator("#feedback")).to_be_focused()
        page.keyboard.press("Tab")
        expect(page.get_by_role("button", name="Tentar novamente", exact=True)).to_be_focused()


def test_cancel_with_escape_returns_focus_without_write(web_context, web_page):
    # Arrange
    page = open_incidents(web_context, web_page, UUID(int=5))
    action = page.get_by_role("button", name="Registrar contenção", exact=True)
    action.focus()
    # Act
    page.keyboard.press("Enter")
    expect(page.locator("#incident-text")).to_be_focused()
    page.keyboard.press("Escape")
    # Assert
    expect(action).to_be_focused()
    assert not any("/transitions" in url for _, url, _ in web_page[2])
