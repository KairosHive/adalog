"""Layout invariants: the workspace must fill the viewport and no panel may collapse to a
sliver. Guards the structural bug where the panels crammed into the top ~150px with a void
below. Skips cleanly if the bundle isn't built or Playwright's browser is absent."""
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


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def bridge(tmp_path):
    import asyncio

    from adalog.adapters.registry import AdapterRegistry
    from adalog.sense.devices import BUILTIN
    from adalog.sense.bridge.server import SenseBridge
    from adalog.sense.service import RecorderService

    reg = AdapterRegistry()
    reg.register_all(BUILTIN)
    svc = RecorderService(sessions_root=tmp_path / "sessions", registry=reg, include_entrypoints=False)
    port = _free_port()
    loop = asyncio.new_event_loop()
    bridge_obj = {}

    def run():
        asyncio.set_event_loop(loop)
        b = SenseBridge(svc, host="127.0.0.1", port=port)
        bridge_obj["b"] = b
        loop.run_until_complete(b.start())
        loop.run_forever()

    threading.Thread(target=run, daemon=True).start()
    time.sleep(0.6)
    yield f"http://127.0.0.1:{port}"
    loop.call_soon_threadsafe(loop.stop)


def _page(p):
    import os
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(Path.home() / ".cache" / "ms-playwright"))
    browser = p.chromium.launch(headless=True)
    return browser, browser.new_page(viewport={"width": 1400, "height": 900})


def test_workspace_fills_viewport_and_panels_not_squished(bridge):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        try:
            browser, page = _page(p)
        except Exception as exc:
            pytest.skip(f"no chromium: {exc}")
        page.goto(bridge, wait_until="networkidle")
        page.wait_for_selector(".panel", timeout=5000)
        time.sleep(0.3)

        # the workspace must fill the viewport height (not collapse to ~150px)
        ws = page.evaluate(
            "() => { const w = document.querySelector('[data-testid=workspace]');"
            " const r = w.getBoundingClientRect(); return { height: r.height, bottom: r.bottom }; }")
        assert ws["height"] > 600, f"workspace collapsed (height={ws['height']:.0f})"
        assert ws["bottom"] > 820, f"workspace does not reach near viewport bottom (bottom={ws['bottom']:.0f})"

        # no rendered panel may be a squished sliver
        heights = page.evaluate(
            "() => [...document.querySelectorAll('.panel')].map(p => p.getBoundingClientRect().height)")
        assert heights, "no panels rendered"
        assert min(heights) > 150, f"a panel is squished: heights={[round(h) for h in heights]}"

        browser.close()


def test_transport_bar_and_clock_visible(bridge):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        try:
            browser, page = _page(p)
        except Exception as exc:
            pytest.skip(f"no chromium: {exc}")
        page.goto(bridge, wait_until="networkidle")
        page.wait_for_selector("[data-testid=transport]", timeout=5000)
        assert page.locator("[data-testid=clock]").is_visible(), "master clock not visible"
        browser.close()
