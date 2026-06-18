"""End-to-end: RecorderService records a multimodal session and reads it back."""
import time

from adalog.adapters.registry import AdapterRegistry
from adalog.core.config_store import ConfigStore
from adalog.core.reader import read_session
from adalog.sense.devices import TextAdapter
from adalog.sense.devices.eeg_muse import EegMuseAdapter
from adalog.sense.service import RecorderService
from adalog.store.local import LocalStore


class _FakeInfo:
    def channel_count(self): return 4
    def nominal_srate(self): return 256.0
    def desc(self): raise RuntimeError("no desc")


class _FakeInlet:
    def __init__(self): self.n = 0
    def info(self): return _FakeInfo()
    def pull_chunk(self, timeout, max_samples):
        # stream continuously (like real hardware) so preview AND recording both see data
        import time as _t
        _t.sleep(0.004)
        base = 50.0 + self.n * (4 / 256.0)
        self.n += 1
        return [[1.0, 2.0, 3.0, 4.0] for _ in range(4)], [base + i / 256.0 for i in range(4)]
    def time_correction(self): return 0.0
    def close_stream(self): pass


class FakeEeg(EegMuseAdapter):
    def _make_inlet(self):
        return _FakeInlet()


def _service(tmp_path):
    reg = AdapterRegistry()
    reg.register_all([FakeEeg, TextAdapter])
    return RecorderService(sessions_root=tmp_path / "sessions", registry=reg,
                           config=ConfigStore(tmp_path / "config.json"),
                           store=LocalStore(tmp_path / "store"), include_entrypoints=False)


def test_service_records_eeg_and_text(tmp_path):
    svc = _service(tmp_path)
    assert {d["id"] for d in svc.list_devices()} == {"eeg_muse", "text"}

    info = svc.session_create(user="u_test", label="run1", tags=["eeg", "writing"])
    sid = info["session_id"]
    svc.device_arm(adapter_id="eeg_muse", instance_id="0")
    arm_text = svc.device_arm(adapter_id="text", instance_id="0")
    assert arm_text["node_id"] == "text#0"
    svc.session_arm()
    svc.session_start()

    # eeg streams from the fake inlet (supervisor thread); feed text via device_ingest
    time.sleep(0.1)
    r = svc.device_ingest(node_id="text#0", batch=[{"kind": "word", "word": "hallo", "t_browser_ns": svc.clock.now_mono_ns()}])
    assert r["accepted"] == 1

    out = svc.session_stop(publish=True)
    assert out["state"] == "complete"

    rs = read_session(out["manifest_path"])
    assert rs.stream("eeg").array.shape[0] >= 8  # at least 2 chunks of 4
    assert rs.stream("eeg").array.shape[1] == 4
    assert [w["word"] for w in rs.stream("text").records] == ["hallo"]
    assert rs.manifest.tags == ["eeg", "writing"]

    # published to the store and queryable
    rows = svc.store.index.query(modality="eeg")
    assert any(row["session_id"] == sid for row in rows)


def test_ingest_dropped_when_not_recording(tmp_path):
    svc = _service(tmp_path)
    svc.session_create(user="u_test")
    svc.device_arm(adapter_id="text", instance_id="0")
    # not started yet -> dropped
    r = svc.device_ingest(node_id="text#0", batch=[{"kind": "word", "word": "x", "t_browser_ns": 1}])
    assert r == {"accepted": 0, "dropped": 1}
    svc.session_arm(); svc.session_start()
    svc.session_pause()
    r2 = svc.device_ingest(node_id="text#0", batch=[{"kind": "word", "word": "y", "t_browser_ns": 2}])
    assert r2["accepted"] == 0 and r2["dropped"] == 1
    svc.session_resume()
    svc.session_stop()
