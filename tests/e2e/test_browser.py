"""Browser e2e (spec milestone 8c/8d): load the built SPA against a live bridge,
arm a device, record, stop — and verify the produced session is valid.

Skips cleanly if the frontend bundle isn't built or Playwright's browser is absent.
"""
import threading
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

REPO = Path(__file__).resolve().parents[2]
BUILD = REPO / "frontend" / "build"

playwright = pytest.importorskip("playwright.sync_api")
if not (BUILD / "index.html").exists():
    pytest.skip("frontend not built (run: cd frontend && pnpm build)", allow_module_level=True)


@pytest.fixture
def bridge(tmp_path):
    import asyncio

    from adalog.adapters.registry import AdapterRegistry
    from adalog.core.config_store import ConfigStore
    from adalog.sense.bridge.server import SenseBridge
    from adalog.sense.devices import MeteoAdapter, TextAdapter
    from adalog.sense.service import RecorderService
    from adalog.store.local import LocalStore

    reg = AdapterRegistry()
    reg.register_all([TextAdapter, MeteoAdapter])
    svc = RecorderService(sessions_root=tmp_path / "sessions", registry=reg,
                          config=ConfigStore(tmp_path / "config.json"),
                          store=LocalStore(tmp_path / "store"), include_entrypoints=False)
    loop = asyncio.new_event_loop()
    holder = {}

    def run():
        asyncio.set_event_loop(loop)
        b = SenseBridge(svc, host="127.0.0.1", port=8401)
        holder["b"] = b
        loop.run_until_complete(b.start())
        loop.run_forever()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    time.sleep(0.6)
    yield "http://127.0.0.1:8401", svc
    loop.call_soon_threadsafe(loop.stop)


def test_record_flow_in_browser(bridge):
    import os
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(Path.home() / ".cache" / "ms-playwright"))
    from playwright.sync_api import sync_playwright

    url, svc = bridge
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as exc:
            pytest.skip(f"no chromium for playwright: {exc}")
        page = browser.new_page()
        page.goto(url, wait_until="networkidle")

        # backend connection indicator
        page.wait_for_selector("text=backend connected", timeout=5000)
        # the three panels render
        assert page.locator("text=Recorder").count() >= 1
        assert page.locator("text=Devices").count() >= 1

        # new session -> arm text -> record -> stop (target by data-testid to avoid
        # the "Recorder" panel-title / "● Record" substring collision)
        page.click("[data-testid=new-session]")
        page.wait_for_selector("[data-testid=arm-text]", timeout=3000)
        page.click("[data-testid=arm-text]")
        page.wait_for_selector("[data-testid=record]:not([disabled])", timeout=3000)
        page.click("[data-testid=record]")
        page.wait_for_selector("[data-testid=stop]", timeout=3000)
        time.sleep(0.4)
        page.click("[data-testid=stop]")
        time.sleep(0.5)
        browser.close()

    # the backend produced a valid, complete session
    from adalog.core.reader import read_session
    sessions = list((svc.sessions_root).rglob("manifest.json"))
    assert sessions, "no session written"
    rs = read_session(sessions[0])
    assert rs.manifest.status == "complete"
    assert rs.manifest.stream("text") is not None
