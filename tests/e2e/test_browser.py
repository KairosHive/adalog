"""Browser e2e (spec milestone 8c/8d + hyperscanning + per-device monitors):
load the built SPA against a live bridge, arm devices (incl. two EEG instances for
hyperscanning), record via the in-browser text input, stop — and verify the produced
session has both subjects' streams plus the typed words.

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


class _FInfo:
    def channel_count(self): return 4
    def nominal_srate(self): return 256.0
    def desc(self): raise RuntimeError("no desc")


class _FInlet:
    def __init__(self): self.n = 0
    def info(self): return _FInfo()
    def pull_chunk(self, timeout, max_samples):
        if self.n >= 2000:
            return [], []
        base = 10.0 + self.n * (4 / 256.0)
        self.n += 1
        return [[1.0, 2.0, 3.0, 4.0] for _ in range(4)], [base + i / 256.0 for i in range(4)]
    def time_correction(self): return 0.0
    def close_stream(self): pass


@pytest.fixture
def bridge(tmp_path):
    import asyncio

    from adalog.adapters.registry import AdapterRegistry
    from adalog.core.config_store import ConfigStore
    from adalog.sense.bridge.server import SenseBridge
    from adalog.sense.devices import TextAdapter
    from adalog.sense.devices.eeg_muse import EegMuseAdapter
    from adalog.sense.service import RecorderService
    from adalog.store.local import LocalStore

    class FakeEeg(EegMuseAdapter):
        def _make_inlet(self):
            return _FInlet()

    reg = AdapterRegistry()
    reg.register_all([FakeEeg, TextAdapter])
    svc = RecorderService(sessions_root=tmp_path / "sessions", registry=reg,
                          config=ConfigStore(tmp_path / "config.json"),
                          store=LocalStore(tmp_path / "store"), include_entrypoints=False)
    loop = asyncio.new_event_loop()

    def run():
        asyncio.set_event_loop(loop)
        b = SenseBridge(svc, host="127.0.0.1", port=8401)
        loop.run_until_complete(b.start())
        loop.run_forever()

    threading.Thread(target=run, daemon=True).start()
    time.sleep(0.6)
    yield "http://127.0.0.1:8401", svc
    loop.call_soon_threadsafe(loop.stop)


def test_hyperscanning_record_flow_with_monitors(bridge):
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

        page.click("[data-testid=new-session]")
        page.wait_for_selector("[data-testid=arm-eeg_muse]", timeout=3000)
        # hyperscanning: two EEG subjects + one text source
        page.click("[data-testid=arm-eeg_muse]")
        page.click("[data-testid=arm-eeg_muse]")
        page.click("[data-testid=arm-text]")
        page.wait_for_selector("[data-testid=record]:not([disabled])", timeout=3000)
        page.click("[data-testid=record]")
        page.wait_for_selector("[data-testid=stop]", timeout=3000)

        # three per-device monitor cards (two EEG instances + text)
        nodes = page.locator(".monitors .node").all_inner_texts()
        assert "eeg_muse#0" in nodes and "eeg_muse#1" in nodes and "text#0" in nodes

        # the EEG monitor must actually receive data over the data plane and draw a
        # trace (proves node-id URL encoding + GOOF decode end-to-end, not just a card)
        time.sleep(0.8)
        drew = page.evaluate(
            """() => {
                const c = document.querySelector('.monitors canvas');
                if (!c) return false;
                const ctx = c.getContext('2d');
                const d = ctx.getImageData(0, 0, c.width, c.height).data;
                for (let i = 3; i < d.length; i += 4) if (d[i] !== 0) return true;  // any non-transparent pixel
                return false;
            }"""
        )
        assert drew, "EEG monitor canvas is blank — data plane delivered no frames"

        # record words through the in-browser text input (type incrementally like a
        # real user so per-keystroke word-onset detection fires)
        ta = page.locator("[data-testid^=text-input-]").first
        ta.click()
        ta.press_sequentially("hyperscan works ", delay=15)
        time.sleep(0.4)
        page.click("[data-testid=stop]")
        time.sleep(0.5)
        browser.close()

    from adalog.core.reader import read_session
    sessions = list(svc.sessions_root.rglob("manifest.json"))
    assert sessions, "no session written"
    rs = read_session(sessions[0])
    ids = {s.id for s in rs.manifest.streams}
    assert {"eeg", "eeg-1", "text"} <= ids, f"missing streams: {ids}"
    assert rs.stream("eeg").array.shape[0] > 0
    assert rs.stream("eeg-1").array.shape[0] > 0
    words = [r.get("word") for r in (rs.stream("text").records or [])]
    assert "works" in words, f"text not recorded: {words}"
