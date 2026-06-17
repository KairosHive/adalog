import threading
import time

from adalog.adapters.base import AdapterInfo
from adalog.adapters.context import AdapterContext
from adalog.adapters.templates import (
    RestPollDevice,
    SerialDevice,
    UiSourceDevice,
)
from adalog.core.spec import Channel, StreamSpec


def _ctx(emitted, registered=None):
    return AdapterContext(emit_fn=emitted.append, now_mono_ns=lambda: 1_000_000,
                          register_fn=(registered.append if registered is not None else None), config={})


def test_rest_poll_dedups_and_emits():
    class Meteo(RestPollDevice):
        info = AdapterInfo(id="meteo", title="Meteo", category="environment")

        def __init__(self):
            self._rows = [[{"tag": "a", "v": 1}], [{"tag": "a", "v": 1}, {"tag": "b", "v": 2}]]
            self._i = 0

        def declare_streams(self):
            return [self._default_spec([Channel("v")])]

        def fetch(self):
            r = self._rows[min(self._i, len(self._rows) - 1)]
            self._i += 1
            return r

        def dedup_key(self, record):
            return record["tag"]

    emitted = []
    a = Meteo()
    a.open(_ctx(emitted))
    a.cfg.poll.interval_s = 0.01
    t = threading.Thread(target=a.start, daemon=True)
    t.start()
    time.sleep(0.05)
    a.stop()
    t.join(timeout=1)
    tags = [p.payload["tag"] for p in emitted]
    assert tags[:2] == ["a", "b"]  # 'a' emitted once, then 'b'; repeated 'a' deduped


def test_ui_source_on_ingest_batch():
    class Drawing(UiSourceDevice):
        info = AdapterInfo(id="drawing", title="Drawing", requires="browser")

        def declare_streams(self):
            return [StreamSpec(id="pentrace", modality="drawing", encoding="pentrace", timing_mode="per_sample")]

        def handle_item(self, item):
            if item.get("kind") == "pen":
                return self.emit_record("pentrace", {"x": item["x"], "y": item["y"]}, item.get("t_browser_ns"))
            return 0

    emitted = []
    a = Drawing()
    a.open(_ctx(emitted))
    n = a.on_ingest({"batch": [{"kind": "pen", "x": 0.1, "y": 0.2, "t_browser_ns": 5},
                               {"kind": "pen", "x": 0.3, "y": 0.4, "t_browser_ns": 6}]})
    assert n == 2
    assert [p.payload for p in emitted] == [{"x": 0.1, "y": 0.2}, {"x": 0.3, "y": 0.4}]
    assert emitted[0].device_ts_ns == 5


def test_serial_parse_loop():
    class FakeSerial:
        def __init__(self, lines):
            self._lines = list(lines)

        def readline(self):
            return self._lines.pop(0) if self._lines else b""

        def close(self):
            pass

    class Ecg(SerialDevice):
        info = AdapterInfo(id="ecg", title="ECG", category="cardio")

        def declare_streams(self):
            return [StreamSpec(id="ecg", modality="ecg", encoding="csv_ts", timing_mode="per_sample",
                               channels=[Channel("raw")])]

        def _make_serial(self):
            return FakeSerial([b"512\n", b"513\n", b"514\n"])

        def parse(self, raw):
            return [{"raw": int(raw.strip())}]

    emitted = []
    a = Ecg()
    a.open(_ctx(emitted))
    t = threading.Thread(target=a.start, daemon=True)
    t.start()
    time.sleep(0.05)
    a.stop()
    t.join(timeout=1)
    assert [p.payload["raw"] for p in emitted] == [512, 513, 514]


def test_template_smoke_imports():
    # Construction of hardware templates without opening must not require the hardware libs.
    from adalog.adapters.templates import AudioDevice, LSLDevice, WebSocketDevice
    assert LSLDevice.template_name == "lsl"
    assert AudioDevice.provenance == "device_portaudio"
    assert WebSocketDevice().config_schema()["ws"]["url"].kind == "string"
