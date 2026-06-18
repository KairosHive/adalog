"""EEG headset-quality (HSI) and ECG BPM/HRV surfaced through adapter status().quality —
native reproduction of the old eeg.gfi / ecg.gfi processing, no goofi."""
import numpy as np

from adalog.adapters.context import AdapterContext
from adalog.core.dsp import HSI_BAD, HSI_DISCONNECTED, HSI_GOOD
from adalog.sense.devices import EcgSerialAdapter, EegMuseAdapter


def _ctx(config=None):
    return AdapterContext(emit_fn=lambda p: None, now_mono_ns=lambda: 1_000_000, config=config or {})


# ---- EEG HSI ----
class _Info:
    def channel_count(self): return 4
    def nominal_srate(self): return 256.0
    def desc(self): raise RuntimeError("no desc")


class _Inlet:
    def info(self): return _Info()
    def pull_chunk(self, timeout, max_samples): return [], []
    def time_correction(self): return 0.0
    def close_stream(self): pass


class _FakeEeg(EegMuseAdapter):
    def _make_inlet(self): return _Inlet()


def test_eeg_hsi_disconnected_before_data():
    a = _FakeEeg(); a.open(_ctx())
    q = a.status().quality
    assert q["status"] == HSI_DISCONNECTED
    assert q["hsi"] == [HSI_DISCONNECTED] * 4


def test_eeg_hsi_good_for_clean_signal():
    a = _FakeEeg(); a.open(_ctx())
    rng = np.random.default_rng(0)
    a._recent.extend(rng.normal(0, 5.0, size=(512, 4)))   # clean ~5 µV
    q = a.status().quality
    assert q["status"] == HSI_GOOD
    assert q["hsi"] == [HSI_GOOD] * 4
    assert len(q["channels"]) == 4


def test_eeg_hsi_flags_noisy_channel_and_strips_aux():
    a = _FakeEeg(); a.open(_ctx())
    # rename the 4th channel to an AUX channel — it must be excluded from quality
    a._ch_names = ["TP9", "AF7", "AF8", "Right AUX"]
    rng = np.random.default_rng(1)
    buf = rng.normal(0, 5.0, size=(512, 4))
    buf[:, 1] += rng.normal(0, 400.0, size=512)   # AF7 is a loose electrode
    buf[:, 3] += 10_000.0                          # huge AUX — would dominate if not stripped
    a._recent.extend(buf)
    q = a.status().quality
    assert q["channels"] == ["TP9", "AF7", "AF8"]   # AUX dropped
    assert len(q["hsi"]) == 3
    assert q["hsi"][1] == HSI_BAD                    # AF7 flagged
    assert q["hsi"][0] == HSI_GOOD
    assert q["status"] == HSI_BAD


def test_eeg_quality_threshold_is_configurable():
    a = _FakeEeg(); a.open(_ctx({"quality": {"threshold": 10.0}}))
    rng = np.random.default_rng(2)
    a._recent.extend(rng.normal(0, 30.0, size=(512, 4)))   # 30 µV exceeds a 10 µV threshold
    assert a.status().quality["status"] == HSI_BAD


# ---- ECG BPM/HRV ----
class _DummySerial:
    def readline(self): return b""
    def close(self): pass


class _FakeEcg(EcgSerialAdapter):
    def _make_serial(self): return _DummySerial()


def _synth_ecg(fs, bpm, seconds, seed=0):
    rng = np.random.default_rng(seed)
    n = int(fs * seconds); x = np.zeros(n); rr = 60.0 / bpm; t = rr
    while t < seconds - rr * 0.5:
        idx = int(t * fs); w = max(1, int(0.01 * fs))
        lo, hi = max(0, idx - 3 * w), min(n, idx + 3 * w)
        ar = np.arange(lo, hi)
        x[lo:hi] += np.exp(-0.5 * ((ar - idx) / w) ** 2)
        t += rr
    return x + rng.normal(0, 0.01, size=n)


def test_ecg_status_reports_bpm_after_buffering():
    a = _FakeEcg(); a.open(_ctx({"signal": {"sfreq": 256.0}}))
    for v in _synth_ecg(256.0, bpm=72.0, seconds=10.0):
        a.parse(f"{v:.4f}\n".encode())
    a._got = len(a._recent)
    q = a.status().quality
    assert q["bpm"] is not None
    assert abs(q["bpm"] - 72.0) < 4.0
    assert q["n_beats"] >= 8
    for k in ("sdnn", "sdsd", "rmssd"):
        assert q[k] is not None


def test_ecg_status_none_before_enough_data():
    a = _FakeEcg(); a.open(_ctx({"signal": {"sfreq": 256.0}}))
    a.parse(b"512\n")
    q = a.status().quality
    assert q["bpm"] is None and q["n_beats"] == 0


def test_ecg_sfreq_config_flows_to_stream_and_window():
    a = _FakeEcg(); a.open(_ctx({"signal": {"sfreq": 500.0}}))
    assert a.declare_streams()[0].sfreq_nominal == 500.0
    assert a._recent.maxlen == int(10.0 * 500.0)
