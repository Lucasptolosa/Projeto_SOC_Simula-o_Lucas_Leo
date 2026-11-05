from datetime import datetime, timedelta, timezone
import json

import pytest
from playwright.sync_api import expect
from sqlalchemy import func, select

from app.auth.models import AuthSession
from app.detection.models import AlertRecord
from app.logs.models import LogRecord
from app.users.models import User
from test_detection_persistence import record
from test_logs import log_context
from test_web import ORIGIN, browser_login, server_login, web_page


@pytest.fixture
def web_context(log_context):
    client, factory, _, admin, _, password, _ = log_context
    with factory() as db: encoded = db.get(User, admin).password_hash
    return client, factory, password, encoded


def open_import(web_context, web_page):
    page = web_page[0]
    browser_login(page, web_context[2], "log-admin")
    page.get_by_role("link", name="Importar Logs", exact=True).click()
    expect(page.locator("#log-import-panel")).to_be_visible()
    return page


def choose(page, data, raw=False):
    content = data if raw else json.dumps(data)
    page.get_by_label("Arquivo JSON", exact=True).set_input_files({"name": "synthetic.json", "mimeType": "application/json", "buffer": content.encode()})


@pytest.mark.parametrize("actor,expected", [("admin", 200), ("analyst", 403), ("anonymous", 303)])
def test_import_page_requires_admin(web_context, actor, expected):
    # Arrange
    client, _, password, _ = web_context
    if actor == "analyst": server_login(client, password, "log-analyst")
    elif actor == "anonymous": client.cookies.clear()
    # Act
    response = client.get("/app/logs/import", follow_redirects=False)
    # Assert
    assert response.status_code == expected and response.headers["cache-control"] == "no-store"
    if expected != 200: assert 'id="log-import-panel"' not in response.text


def test_mixed_import_and_detection_results(web_context, web_page, log_context):
    # Arrange
    page = open_import(web_context, web_page)
    records = [record(log_context[2], n, n) for n in range(5)]
    choose(page, [*records, {}, records[0]])
    # Act
    page.get_by_role("button", name="Importar Logs", exact=True).click()
    # Assert
    expect(page.locator("#ingestion-summary")).to_have_text("Aceitos: 5 · Rejeitados: 2")
    expect(page.locator("#detection-summary")).to_have_text("Avaliados: 5 · Rejeitados para detecção: 0 · Alerts criados: 1")
    expect(page.locator("#ingestion-rejections")).to_contain_text("duplicate_event_id")
    assert page.locator("#ingestion-rejections tr").count() == 2
    assert page.locator("#log-file").input_value() == ""
    writes = [(url, headers) for method, url, headers in web_page[2] if method == "POST" and url.endswith("/logs/import")]
    assert len(writes) == 1 and writes[0][1]["origin"] == ORIGIN
    assert len(writes[0][1]["x-csrf-token"]) == 64 and writes[0][1]["content-type"] == "application/json"
    with web_context[1]() as db:
        assert db.scalar(select(func.count()).select_from(LogRecord)) == 5
        assert db.scalar(select(func.count()).select_from(AlertRecord)) == 1


def test_duplicate_and_out_of_order_are_distinct(web_context, web_page, log_context):
    # Arrange
    page = open_import(web_context, web_page)
    records = [record(log_context[2], n, n) for n in range(5)]
    choose(page, records)
    page.get_by_role("button", name="Importar Logs", exact=True).click()
    expect(page.locator("#feedback")).to_contain_text("Lote confirmado")
    # Act
    choose(page, records)
    page.get_by_role("button", name="Importar Logs", exact=True).click()
    expect(page.locator("#ingestion-summary")).to_have_text("Aceitos: 0 · Rejeitados: 5")
    rejected = page.locator("#ingestion-rejections").inner_text()
    choose(page, [record(log_context[2], 100, -1)])
    page.get_by_role("button", name="Importar Logs", exact=True).click()
    # Assert
    assert "duplicate_event_id" in rejected
    expect(page.locator("#ingestion-summary")).to_have_text("Aceitos: 1 · Rejeitados: 0")
    expect(page.locator("#detection-summary")).to_have_text("Avaliados: 0 · Rejeitados para detecção: 1 · Alerts criados: 0")
    expect(page.locator("#detection-rejections")).to_contain_text("out_of_order")


@pytest.mark.parametrize("data,raw", [("private-content-not-json", True), ([], False), ({}, False), ([{}]*1001, False)], ids=["json", "empty", "object", "large"])
def test_invalid_file_does_not_send(web_context, web_page, data, raw):
    # Arrange
    page = open_import(web_context, web_page)
    choose(page, data, raw)
    # Act
    page.get_by_role("button", name="Importar Logs", exact=True).click()
    # Assert
    expect(page.locator("#feedback")).to_contain_text("Arquivo JSON inválido" if raw else "1 a 1.000")
    assert not any(method == "POST" and url.endswith("/logs/import") for method, url, _ in web_page[2])
    assert "private-content-not-json" not in page.content()


def test_maximum_batch_is_sent_to_backend_validation(web_context, web_page):
    # Arrange
    page = open_import(web_context, web_page)
    choose(page, [{}]*1000)
    # Act
    page.get_by_role("button", name="Importar Logs", exact=True).click()
    # Assert
    expect(page.locator("#ingestion-summary")).to_have_text("Aceitos: 0 · Rejeitados: 1000")
    assert page.locator("#ingestion-rejections tr").count() == 1000


def test_duplicate_submission_blocked(web_context, web_page, log_context):
    # Arrange
    page = open_import(web_context, web_page)
    choose(page, [record(log_context[2], 1, 1)])
    pending = []
    page.route(ORIGIN + "/logs/import", lambda route: pending.append(route))
    # Act
    page.get_by_role("button", name="Importar Logs", exact=True).click()
    expect(page.get_by_role("button", name="Sair", exact=True)).to_be_disabled()
    page.locator("#log-import-form").evaluate("form => form.dispatchEvent(new Event('submit', {cancelable:true,bubbles:true}))")
    count = len(pending); pending[0].fallback()
    # Assert
    assert count == 1
    expect(page.locator("#ingestion-summary")).to_have_text("Aceitos: 1 · Rejeitados: 0")
    expect(page.get_by_role("button", name="Sair", exact=True)).to_be_enabled()


@pytest.mark.parametrize("failure", ["csrf", "expired", 422, 503])
def test_import_failures_are_safe(web_context, web_page, log_context, failure):
    # Arrange
    page = open_import(web_context, web_page)
    choose(page, [record(log_context[2], 1, 1)])
    if failure == "expired":
        with web_context[1].begin() as db:
            for session in db.scalars(select(AuthSession)):
                session.created_at = datetime.now(timezone.utc)-timedelta(hours=2)
                session.expires_at = datetime.now(timezone.utc)-timedelta(hours=1)
    def fail(route):
        if failure == "csrf":
            headers=route.request.all_headers();headers.pop("x-csrf-token");route.fallback(headers=headers)
        else: route.fulfill(status=failure, json={"detail":"private-error"})
    if failure != "expired": page.route(ORIGIN + "/logs/import", fail)
    # Act
    page.get_by_role("button", name="Importar Logs", exact=True).click()
    # Assert
    if failure == "expired": page.wait_for_url(ORIGIN+"/login?reason=session")
    else: expect(page.locator("#feedback")).to_contain_text("Acesso negado" if failure == "csrf" else "Lote inválido" if failure == 422 else "Não foi possível confirmar")
    assert "private-error" not in page.content()
    assert page.evaluate("localStorage.length + sessionStorage.length") == 0
    with web_context[1]() as db: assert db.scalar(select(func.count()).select_from(LogRecord)) == 0


def test_result_is_not_html_and_mobile_fits(web_context, web_page, log_context, tmp_path):
    # Arrange
    page = open_import(web_context, web_page)
    malicious='<img src=x onerror="window.injected=true">'
    response={"accepted":0,"rejected":1,"rejections":[{"position":1,"reason":"invalid_record","detail":malicious}],
              "detection":{"evaluated":0,"rejected":0,"rejections":[],"alerts_created":0}}
    page.route(ORIGIN+"/logs/import", lambda route:route.fulfill(status=200,json=response))
    choose(page, [{}])
    # Act
    page.get_by_role("button", name="Importar Logs", exact=True).click()
    page.set_viewport_size({"width":390,"height":844})
    # Assert
    expect(page.locator("#ingestion-rejections")).to_contain_text(malicious)
    assert page.locator("#ingestion-rejections img").count()==0 and page.evaluate("window.injected === undefined")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.screenshot(path=str(tmp_path/"import-mobile.png"),full_page=True)
