import pytest
from playwright.sync_api import expect

from test_investigations import investigation_context
from test_logs import log_context
from test_web import web_page
from test_web_investigations import create_investigation, web_context


@pytest.mark.parametrize("dismiss", [False, True])
def test_terminal_decision_preserves_keyboard_focus(web_context, web_page, investigation_context, dismiss):
    # Arrange
    page, _ = create_investigation(web_context, web_page, investigation_context)
    action = page.get_by_role("button", name="Descartar False Positive" if dismiss else "Escalonar para Incident", exact=True)
    action.focus()
    # Act
    page.keyboard.press("Enter")
    if dismiss:
        expect(page.get_by_label("Justificativa", exact=True)).to_be_focused()
        page.keyboard.type("Operação legítima")
        page.get_by_role("button", name="Confirmar descarte", exact=True).focus()
        page.keyboard.press("Enter")
    # Assert
    status = page.locator('[data-investigation-field="status"]')
    expect(status).to_have_text("DISMISSED" if dismiss else "ESCALATED")
    expect(status).to_be_focused()


@pytest.mark.parametrize("status", [409, 422, 503])
def test_failed_decision_preserves_recovery_focus(web_context, web_page, investigation_context, status):
    # Arrange
    page, _ = create_investigation(web_context, web_page, investigation_context)
    page.route("**/investigations/*/false-positive", lambda route: route.fulfill(status=status, json={"detail": "failure"}))
    page.get_by_role("button", name="Descartar False Positive", exact=True).focus()
    page.keyboard.press("Enter")
    page.get_by_label("Justificativa", exact=True).fill("Verificação")
    page.get_by_role("button", name="Confirmar descarte", exact=True).focus()
    # Act
    page.keyboard.press("Enter")
    # Assert
    if status == 422:
        expect(page.locator("#dismiss-error")).to_contain_text("Dados inválidos")
        expect(page.locator("#dismiss-justification")).to_be_focused()
        assert page.locator("#dismiss-justification").get_attribute("tabindex") is None
    elif status == 409:
        expect(page.locator("#feedback")).to_contain_text("Conflito")
        expect(page.locator('[data-investigation-field="status"]')).to_be_focused()
    else:
        expect(page.locator("#feedback")).to_contain_text("Atualize antes")
        expect(page.locator("#feedback")).to_be_focused()


def test_cancel_dismissal_keeps_focus_without_write(web_context, web_page, investigation_context):
    # Arrange
    page, _ = create_investigation(web_context, web_page, investigation_context)
    action = page.get_by_role("button", name="Descartar False Positive", exact=True)
    action.focus()
    # Act
    page.keyboard.press("Enter")
    expect(page.locator("#dismiss-justification")).to_be_focused()
    page.keyboard.press("Escape")
    # Assert
    expect(action).to_be_focused()
    assert not any("/false-positive" in url for _, url, _ in web_page[2])


def test_observation_reload_preserves_keyboard_focus(web_context, web_page, investigation_context):
    # Arrange
    page, _ = create_investigation(web_context, web_page, investigation_context)
    page.get_by_label("Observação", exact=True).fill("Registro por teclado")
    page.get_by_role("button", name="Registrar observação", exact=True).focus()
    # Act
    page.keyboard.press("Enter")
    # Assert
    expect(page.locator("#feedback")).to_have_text("Observação registrada com sucesso.")
    expect(page.locator('[data-investigation-field="status"]')).to_be_focused()
    expect(page.locator("#observation-results")).to_contain_text("Registro por teclado")
