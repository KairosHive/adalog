"""Browser e2e for the device config + discovery UI: the gear expander renders a device's
config_schema, edits are applied, and the values reach the backend adapter on arm.

Skips cleanly if the frontend bundle isn't built or Playwright's browser is absent."""
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


class _FInfo:
    def channel_count(self): return 4
    def nominal_srate(self): return 256.0
    def desc(self): raise RuntimeError("no desc")


class _FInlet:
    def info(self): return _FInfo()
    def pull_chunk(self, timeout, max_samples):
        import time as _t
        _t.sleep(0.01)
        return [], []
    def time_correction(self): return 0.0
    def close_stream(self): pass


@pytest.fixture
def bridge(tmp_path):
    import asyncio

    from adalog.adapters.registry import AdapterRegistry
    from adalog.sense.bridge.server import SenseBridge
    from adalog.sense.devices.eeg_muse import EegMuseAdapter
    from adalog.sense.service import RecorderService

    class FakeEeg(EegMuseAdapter):
        def _make_inlet(self):
            return _FInlet()

    reg = AdapterRegistry()
    reg.register_all([FakeEeg])
    svc = RecorderService(sessions_root=tmp_path / "sessions", registry=reg, include_entrypoints=False)
    loop = asyncio.new_event_loop()

    def run():
        asyncio.set_event_loop(loop)
        b = SenseBridge(svc, host="127.0.0.1", port=8402)
        loop.run_until_complete(b.start())
        loop.run_forever()

    threading.Thread(target=run, daemon=True).start()
    time.sleep(0.6)
    yield "http://127.0.0.1:8402", svc
    loop.call_soon_threadsafe(loop.stop)


def test_device_config_edits_reach_backend(bridge):
    import os
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(Path.home() / ".cache" / "ms-playwright"))
    from playwright.sync_api import sync_playwright

    url, svc = bridge
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as exc:
            pytest.skip(f"no chromium for playwright: {exc}")
        page = browser.new_page(viewport={"width": 1500, "height": 900})
        page.goto(url, wait_until="networkidle")
        page.wait_for_selector("text=backend connected", timeout=5000)
        page.fill("[data-testid=username]", "phil")
        page.click("[data-testid=new-session]")

        # the config gear renders the device's config_schema
        page.wait_for_selector("[data-testid=cfg-eeg_muse]", timeout=3000)
        page.click("[data-testid=cfg-eeg_muse]")
        page.wait_for_selector("span.key:text-is('threshold')", timeout=3000)

        # edit a numeric field, then arm
        th = page.locator("label:has(span.key:text-is('threshold')) input[type=number]")
        th.fill("42")
        th.dispatch_event("change")
        page.click("[data-testid=arm-eeg_muse]")
        page.wait_for_selector(".monitors .node", timeout=3000)
        browser.close()

    # the edited value reached the live backend adapter
    adapter = svc._instances.get("eeg_muse#0")
    assert adapter is not None, "device did not arm"
    assert adapter.cfg.quality.threshold == 42.0
