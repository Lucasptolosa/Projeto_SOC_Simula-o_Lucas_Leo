from concurrent.futures import ThreadPoolExecutor
from http.cookiejar import CookieJar
import ctypes
import json
import os
import platform
import socket
from threading import Thread
from time import perf_counter, sleep
from urllib.request import HTTPCookieProcessor, Request, build_opener

import pytest
from sqlalchemy import func, select
import uvicorn

from app.auth.dependencies import get_auth_settings
from app.detection.models import AlertRecord
from app.incidents.models import Incident
from app.logs.models import LogRecord
from app.main import app
from test_detection_persistence import record
from test_detection_transactions import committed_detection_db
from test_soc_flow import flow


pytestmark = pytest.mark.skipif(os.getenv("RUN_MVP_BENCHMARKS") != "1", reason="Benchmark HTTP opt-in; fora da CI funcional.")


def resources():
    if os.name == "nt":
        class Memory(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                        *[(name, ctypes.c_ulonglong) for name in ("physical", "available", "page", "free_page", "virtual", "free_virtual", "extended")]]
        memory = Memory(); memory.length = ctypes.sizeof(memory)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory))
        total = memory.physical
    else:
        total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    return {"system": platform.system(), "logical_cpus": os.cpu_count(), "ram_gib": round(total / (1024 ** 3), 2),
            "reference_environment_certified": False}


class HttpClient:
    def __init__(self, origin, username, password):
        self.origin = origin
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))
        self.csrf = None
        result = self.call("/auth/login", {"username": username, "password": password})
        self.csrf = result["csrf_token"]

    def call(self, path, payload=None):
        headers = {"Origin": self.origin}
        if payload is not None: headers["Content-Type"] = "application/json"
        if self.csrf: headers["X-CSRF-Token"] = self.csrf
        request = Request(self.origin + path, data=None if payload is None else json.dumps(payload).encode(), headers=headers)
        with self.opener.open(request, timeout=60) as response:
            assert response.status in {200, 201}
            return json.load(response)


@pytest.fixture
def live_api(flow, test_db_settings):
    sock = socket.socket(); sock.bind(("127.0.0.1", 0)); sock.listen(128)
    origin = f"http://127.0.0.1:{sock.getsockname()[1]}"
    previous = app.dependency_overrides[get_auth_settings]
    app.dependency_overrides[get_auth_settings] = lambda: test_db_settings.model_copy(update={"auth_origin": origin, "auth_cookie_secure": False})
    server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False, lifespan="off"))
    thread = Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    try:
        deadline = perf_counter() + 10
        while not server.started and thread.is_alive() and perf_counter() < deadline: sleep(.01)
        assert server.started
        yield origin
    finally:
        server.should_exit = True; thread.join(timeout=10); sock.close()
        app.dependency_overrides[get_auth_settings] = previous
        assert not thread.is_alive()


def test_rnf06_real_http_thousand_logs(flow, live_api):
    # Arrange
    _, session, _, asset, _, password, _ = flow
    client = HttpClient(live_api, "admin-0", password)
    records = [record(asset, n, n) for n in range(1000)]
    # Act
    start = perf_counter()
    response = client.call("/logs/import", records)
    elapsed = perf_counter() - start
    # Assert
    assert (response["accepted"], response["rejected"], response["detection"]["alerts_created"]) == (1000, 0, 1)
    with session() as db:
        assert db.scalar(select(func.count()).select_from(LogRecord)) == 1000
        assert db.scalar(select(func.count()).select_from(AlertRecord)) == 1
    print(json.dumps({"requirement": "RNF06", "seconds": round(elapsed, 6), "threshold_seconds": 15, "resources": resources()}))
    assert elapsed <= 15


def test_rnf05_real_http_five_clients(flow, live_api):
    # Arrange
    if "/alerts" not in app.openapi()["paths"]:
        pytest.skip("GET /alerts depende da integração do PR #57.")
    _, session, _, asset, _, password, _ = flow
    admin = HttpClient(live_api, "admin-0", password)
    for batch in range(10):
        payload = [record(asset, n, n, username=f"benchmark-{n // 20}") for n in range(batch * 1000, (batch + 1) * 1000)]
        assert admin.call("/logs/import", payload)["accepted"] == 1000
    analyst = HttpClient(live_api, "flow-analyst", password)
    with session() as db: alerts = list(db.scalars(select(AlertRecord.id).order_by(AlertRecord.id).limit(100)))
    for alert in alerts:
        investigation = analyst.call("/investigations", {"alert_id": str(alert)})
        analyst.call(f"/investigations/{investigation['id']}/escalate", {})
    with session() as db:
        assert db.scalar(select(func.count()).select_from(LogRecord)) == 10000
        assert db.scalar(select(func.count()).select_from(AlertRecord)) == 500
        assert db.scalar(select(func.count()).select_from(Incident)) == 100
    def measure(_):
        browser = HttpClient(live_api, "flow-analyst", password)
        measurements = []
        for _ in range(20):
            start = perf_counter()
            result = browser.call("/alerts?page=1&page_size=20")
            measurements.append(perf_counter() - start)
            assert result["total"] == 500 and len(result["items"]) == 20
        return measurements
    # Act
    with ThreadPoolExecutor(max_workers=5) as pool:
        measurements = [value for group in pool.map(measure, range(5)) for value in group]
    # Assert
    within = sum(value <= 2 for value in measurements)
    print(json.dumps({"requirement": "RNF05", "requests": len(measurements), "within_two_seconds": within,
                      "maximum_seconds": max(measurements), "resources": resources()}))
    assert len(measurements) == 100 and within >= 90
