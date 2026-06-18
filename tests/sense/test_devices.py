import threading
import time

from adalog.adapters.context import AdapterContext
from adalog.adapters.registry import AdapterRegistry
from adalog.sense.devices import (
    BUILTIN,
    DrawingAdapter,
    EcgSerialAdapter,
    EegMuseAdapter,
    MeteoAdapter,
    MidiAdapter,
    OscAdapter,
    TextAdapter,
)


def _ctx(emitted):
    return AdapterContext(emit_fn=emitted.append, now_mono_ns=lambda: 1_000_000, config={})


def test_catalog_has_8_with_requires_flags():
    reg = AdapterRegistry()
    reg.register_all(BUILTIN)
    assert len(reg.ids()) == 8
    cat = {c["id"]: c for c in reg.catalog()}
    assert cat["text"]["requires"] == "browser"
    assert cat["drawing"]["requires"] == "browser"
    assert cat["eeg_muse"]["requires"] is None


# ---- EEG via a fake LSL inlet ----
class _FakeInfo:
    def channel_count(self):
        return 4

    def nominal_srate(self):
        return 256.0

    def desc(self):
        raise RuntimeError("no desc")  # forces ch0..ch3 fallback


class _FakeInlet:
    def __init__(self):
        self.n = 0

    def info(self):
        return _FakeInfo()

    def pull_chunk(self, timeout, max_samples):
        if self.n >= 3:
            return [], []
        base = 100.0 + self.n * (4 / 256.0)
        self.n += 1
        samples = [[1.0, 2.0, 3.0, 4.0] for _ in range(4)]
        stamps = [base + i / 256.0 for i in range(4)]
        return samples, stamps

    def time_correction(self):
        return 0.0

    def close_stream(self):
        pass


def test_eeg_muse_emits_per_sample_timestamps():
    class FakeEeg(EegMuseAdapter):
        def _make_inlet(self):
            return _FakeInlet()

    emitted = []
    a = FakeEeg()
    a.open(_ctx(emitted))
    specs = a.resolve_streams()
    assert specs[0].id == "eeg" and len(specs[0].channels) == 4
    t = threading.Thread(target=a.start, daemon=True)
    t.start()
    time.sleep(0.05)
    a.stop()
    t.join(timeout=1)
    assert len(emitted) >= 1
    pkt = emitted[0]
    assert pkt.n_samples == 4
    assert pkt.per_sample_ts is not None and len(pkt.per_sample_ts) == 4


def test_ecg_parse():
    a = EcgSerialAdapter()
    assert a.parse(b"512\n") == [{"raw": 512}]
    assert a.parse(b"  \n") == []
    assert a.declare_streams()[0].id == "ecg"


def test_text_word_onset():
    emitted = []
    a = TextAdapter()
    a.open(_ctx(emitted))
    a.on_ingest({"kind": "word", "word": "hello", "t_browser_ns": 42})
    assert emitted[0].payload == {"word": "hello"}
    assert emitted[0].device_ts_ns == 42


def test_drawing_pen_and_snapshot():
    import base64
    emitted = []
    a = DrawingAdapter()
    a.open(_ctx(emitted))
    a.on_ingest({"kind": "pen", "x": 0.5, "y": 0.6, "pressure": 0.9, "stroke_id": 3, "t_browser_ns": 1})
    png = b"\x89PNG\r\n\x1a\nFAKE"
    a.on_ingest({"kind": "snapshot", "png_b64": base64.b64encode(png).decode(), "t_browser_ns": 2})
    assert emitted[0].stream_id == "pentrace"
    assert emitted[0].payload["x"] == 0.5
    assert emitted[1].stream_id == "snapshot"
    assert emitted[1].payload == png


def test_midi_fake_input():
    class FakeMsg:
        def dict(self):
            return {"type": "note_on", "note": 60, "velocity": 100}

    class FakePort:
        def __init__(self, cb):
            self._cb = cb

        def close(self):
            pass

    class FakeMidi(MidiAdapter):
        def _make_input(self):
            port = FakePort(self._on_msg)
            # deliver one message synchronously
            self._on_msg(FakeMsg())
            return port

    emitted = []
    a = FakeMidi()
    a.open(_ctx(emitted))
    assert emitted[0].payload == {"type": "note_on", "note": 60, "velocity": 100}


def test_osc_message_decode():
    # exercise pure decode logic without open() (open() fails fast when oscpy is absent)
    emitted = []
    a = OscAdapter()
    a.ctx = _ctx(emitted)
    a._seq = 0
    a._on_message(b"/synth/freq", 440.0)
    a._on_message(b"/chord", 1, 2, 3)
    assert emitted[0].payload == {"address": "/synth/freq", "value": 440.0}
    assert emitted[1].payload == {"address": "/chord", "value": [1, 2, 3]}


def test_osc_arm_without_backend_is_clean_device_error():
    # OSC must fail at arm (open), not silently in the start() thread
    from adalog.adapters.base import DeviceUnavailable
    import importlib.util
    if importlib.util.find_spec("oscpy") is not None:
        import pytest
        pytest.skip("oscpy installed; this test covers the missing-backend path")
    a = OscAdapter()
    import pytest
    with pytest.raises(DeviceUnavailable):
        a.open(_ctx([]))


def test_meteo_merge_and_dedup():
    mag = [["time_tag", "bx_gsm", "by_gsm", "bz_gsm", "bt"],
           ["2026-06-17T00:00:00", "1.0", "2.0", "-3.0", "4.0"]]
    plasma = [["time_tag", "density", "speed", "temperature"],
              ["2026-06-17T00:00:00", "5.0", "400.0", "100000.0"]]

    class FakeMeteo(MeteoAdapter):
        def _get_json(self, url):
            return mag if "mag" in url else plasma

    emitted = []
    a = FakeMeteo()
    a.open(_ctx(emitted))
    rows = a.fetch()
    assert rows[0]["time_tag"] == "2026-06-17T00:00:00"
    assert rows[0]["bx_gsm"] == 1.0 and rows[0]["speed"] == 400.0
    # dedup: same time_tag emitted once
    a.emit_record(rows[0]); a._seen = a.dedup_key(rows[0])
    assert a.dedup_key(rows[0]) == "2026-06-17T00:00:00"
