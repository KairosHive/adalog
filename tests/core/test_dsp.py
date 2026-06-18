"""Native DSP reproduction of the old goofi .gfi processing (EEG HSI + ECG HRV)."""
import numpy as np

from adalog.core.dsp import (
    HSI_BAD,
    HSI_GOOD,
    eeg_headset_status,
    hrv_metrics,
    notch_filter,
    pan_tompkins_peaks,
)


def test_notch_attenuates_line_freq_keeps_signal():
    fs = 256.0
    t = np.arange(0, 4.0, 1 / fs)
    line = np.sin(2 * np.pi * 60 * t)        # 60 Hz powerline
    brain = np.sin(2 * np.pi * 10 * t)       # 10 Hz alpha
    y = notch_filter(line + brain, fs, 60.0, 10.0)
    # after warm-up, the 60 Hz component is strongly suppressed...
    tail = slice(int(fs), None)
    resid_line = notch_filter(line, fs, 60.0, 10.0)[tail]
    assert np.sqrt(np.mean(resid_line ** 2)) < 0.2   # >80% line attenuation
    # ...while the 10 Hz alpha is largely preserved
    resid_brain = notch_filter(brain, fs, 60.0, 10.0)[tail]
    assert np.sqrt(np.mean(resid_brain ** 2)) > 0.6
    assert y.shape == line.shape


def test_notch_handles_multichannel_and_empty():
    fs = 256.0
    x = np.random.randn(100, 4)
    assert notch_filter(x, fs).shape == (100, 4)
    assert notch_filter(np.empty((0, 3)), fs).shape == (0, 3)


def test_headset_status_good_for_clean_low_amplitude():
    fs = 256.0
    rng = np.random.default_rng(0)
    buf = rng.normal(0, 5.0, size=(512, 4))   # ~5 µV clean EEG, well under 100
    overall, per_ch = eeg_headset_status(buf, fs, threshold=100.0)
    assert overall == HSI_GOOD
    assert per_ch == [HSI_GOOD] * 4


def test_headset_status_bad_when_amplitude_exceeds_threshold():
    fs = 256.0
    rng = np.random.default_rng(1)
    buf = rng.normal(0, 5.0, size=(512, 4))
    buf[:, 2] += rng.normal(0, 400.0, size=512)   # channel 2 is a noisy/loose electrode
    overall, per_ch = eeg_headset_status(buf, fs, threshold=100.0)
    assert overall == HSI_BAD
    assert per_ch[2] == HSI_BAD
    assert per_ch[0] == HSI_GOOD


def _synth_ecg(fs: float, bpm: float, seconds: float, jitter_ms: float = 0.0, seed: int = 0):
    """Synthesise an ECG-like trace with Gaussian R-peaks at the given (jittered) rate."""
    rng = np.random.default_rng(seed)
    n = int(fs * seconds)
    x = np.zeros(n)
    rr = 60.0 / bpm
    t = rr
    peak_times = []
    while t < seconds - rr * 0.5:
        jt = t + rng.normal(0, jitter_ms / 1000.0)
        peak_times.append(jt)
        idx = int(jt * fs)
        width = max(1, int(0.01 * fs))
        lo, hi = max(0, idx - 3 * width), min(n, idx + 3 * width)
        rng_idx = np.arange(lo, hi)
        x[lo:hi] += 1.0 * np.exp(-0.5 * ((rng_idx - idx) / width) ** 2)
        t += rr
    x += rng.normal(0, 0.01, size=n)   # mild baseline noise
    return x, peak_times


def test_pan_tompkins_detects_regular_beats():
    fs = 256.0
    x, peak_times = _synth_ecg(fs, bpm=60.0, seconds=10.0)
    peaks = pan_tompkins_peaks(x, fs)
    # should find ~one beat per second (allow ±1 for edges)
    assert abs(len(peaks) - len(peak_times)) <= 1
    m = hrv_metrics(peaks, fs)
    assert m["bpm"] is not None
    assert abs(m["bpm"] - 60.0) < 3.0


def test_hrv_regular_is_low_variability_jittered_is_higher():
    fs = 256.0
    reg, _ = _synth_ecg(fs, bpm=70.0, seconds=20.0, jitter_ms=0.0, seed=2)
    jit, _ = _synth_ecg(fs, bpm=70.0, seconds=20.0, jitter_ms=30.0, seed=3)
    m_reg = hrv_metrics(pan_tompkins_peaks(reg, fs), fs)
    m_jit = hrv_metrics(pan_tompkins_peaks(jit, fs), fs)
    assert abs(m_reg["bpm"] - 70.0) < 3.0
    assert m_jit["rmssd"] > m_reg["rmssd"]   # jitter raises beat-to-beat variability


def test_hrv_handles_too_few_beats():
    m = hrv_metrics(np.array([100]), 256.0)
    assert m == {"bpm": None, "sdnn": None, "sdsd": None, "rmssd": None, "n_beats": 1}


def test_pan_tompkins_robust_to_single_transient_artifact():
    # one electrode pop / motion spike must NOT collapse detection of every real beat
    fs = 256.0
    x, peak_times = _synth_ecg(fs, bpm=60.0, seconds=10.0)
    i = int(5.0 * fs)
    x[i:i + 6] += 12.0   # large transient artifact (≫ QRS amplitude)
    peaks = pan_tompkins_peaks(x, fs)
    m = hrv_metrics(peaks, fs)
    assert m["bpm"] is not None, "a single artifact blanked the BPM readout"
    assert abs(m["bpm"] - 60.0) < 6.0, f"artifact corrupted BPM: {m['bpm']}"


def test_hrv_successive_diffs_exclude_gaps():
    # perfectly regular 1 Hz beats with ONE missed beat (a 2 s gap). The only "variation" is the
    # artificial gap; gap-aware HRV must not let it inflate RMSSD/SDSD.
    fs = 256.0
    peaks = np.array([int(t * fs) for t in (1, 2, 3, 5, 6, 7, 8)])  # missing the beat at t=4
    m = hrv_metrics(peaks, fs)
    assert m["rmssd"] is not None
    assert m["rmssd"] < 50.0, f"gap inflated RMSSD to {m['rmssd']} ms"
    assert m["sdsd"] < 50.0, f"gap inflated SDSD to {m['sdsd']} ms"
