"""Hyperscanning: multiple instances of one device record to distinct, aligned streams."""
import time

from adalog.adapters.registry import AdapterRegistry
from adalog.core.config_store import ConfigStore
from adalog.core.reader import read_session
from adalog.sense.devices.eeg_muse import EegMuseAdapter
from adalog.sense.service import RecorderService
from adalog.store.local import LocalStore


class _FInfo:
    def channel_count(self): return 4
    def nominal_srate(self): return 256.0
    def desc(self): raise RuntimeError("no desc")


def _make_inlet(start):
    class _FInlet:
        def __init__(self): self.n = 0
        def info(self): return _FInfo()
        def pull_chunk(self, timeout, max_samples):
            import time as _t
            _t.sleep(0.004)  # stream continuously so preview + recording both see data
            base = start + self.n * (4 / 256.0)
            self.n += 1
            return [[1.0, 2.0, 3.0, 4.0] for _ in range(4)], [base + i / 256.0 for i in range(4)]
        def time_correction(self): return 0.0
        def close_stream(self): pass
    return _FInlet()


def _service(tmp_path):
    reg = AdapterRegistry()

    class FakeEeg(EegMuseAdapter):
        _start = 100.0
        def _make_inlet(self):
            return _make_inlet(FakeEeg._start)

    reg.register(FakeEeg)
    return RecorderService(sessions_root=tmp_path / "sessions", registry=reg,
                           config=ConfigStore(tmp_path / "config.json"),
                           store=LocalStore(tmp_path / "store"), include_entrypoints=False)


def test_two_eeg_instances_record_distinct_streams(tmp_path):
    svc = _service(tmp_path)
    svc.session_create(user="dyad", label="hyperscan", tags=["dyad"])

    a0 = svc.device_arm(adapter_id="eeg_muse", instance_id="0")
    a1 = svc.device_arm(adapter_id="eeg_muse", instance_id="1")
    assert a0["node_id"] == "eeg_muse#0"
    assert a1["node_id"] == "eeg_muse#1"
    # distinct session stream ids (no collision)
    s0 = a0["streams"][0]["id"]
    s1 = a1["streams"][0]["id"]
    assert s0 == "eeg"          # instance 0 keeps the clean id
    assert s1 == "eeg-1"        # instance 1 namespaced
    assert s0 != s1

    svc.session_arm()
    svc.session_start()
    time.sleep(0.15)
    out = svc.session_stop()

    rs = read_session(out["manifest_path"])
    # both subjects' EEG present as separate aligned streams
    assert rs.stream("eeg").array.shape[1] == 4
    assert rs.stream("eeg-1").array.shape[1] == 4
    assert rs.stream("eeg").array.shape[0] >= 8
    assert rs.stream("eeg-1").array.shape[0] >= 8
    # both reference the same adapter but are distinct manifest entries
    ids = {st.id for st in rs.manifest.streams}
    assert {"eeg", "eeg-1"} <= ids


def test_single_instance_keeps_clean_id(tmp_path):
    svc = _service(tmp_path)
    svc.session_create(user="solo")
    a = svc.device_arm(adapter_id="eeg_muse", instance_id="0")
    assert a["streams"][0]["id"] == "eeg"  # no suffix when alone
