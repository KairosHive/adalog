"""Pure-numpy DSP for native reproduction of the old goofi ``.gfi`` signal processing.

adalog is goofi-free: the EEG headset-quality and ECG heart-rate metrics that the old
adalog computed inside goofi patches (``eeg.gfi`` → ``EEGHeadsetDetection``; ``ecg.gfi`` →
``CardioRespiratoryVariability``) are reproduced here with numpy only — no scipy, no
neurokit2, no goofi. Functions are stateless; adapters own the rolling buffers and call in
from ``status()``.

EEG quality faithfully follows the patch chain: notch(60 Hz, Q=10) → demean → centre →
``|x|`` → per-channel max vs a threshold (the patch set 100 µV). 0=disconnected, 1=bad
(amplitude too high / not worn), 2=good — matching the old ``/eeg_quality`` 0/1/2 codes.

ECG uses a numpy Pan–Tompkins R-peak detector → RR intervals → BPM + time-domain HRV
(SDNN/SDSD/RMSSD), the time-domain subset of what neurokit's ``hrv`` produced.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

# headset-status codes (mirror the old /eeg_quality OSC values)
HSI_DISCONNECTED = 0
HSI_BAD = 1
HSI_GOOD = 2


def notch_filter(x: np.ndarray, fs: float, f0: float = 60.0, Q: float = 10.0) -> np.ndarray:
    """Causal RBJ biquad notch, applied along axis 0 (samples). Accepts 1-D or 2-D
    (samples × channels). Returns float64 of the same shape. A no-op if fs/f0 invalid."""
    x = np.asarray(x, dtype=np.float64)
    if x.size == 0 or fs <= 0 or f0 <= 0 or f0 >= fs / 2:
        return x.copy()
    w0 = 2.0 * np.pi * f0 / fs
    cosw, sinw = np.cos(w0), np.sin(w0)
    alpha = sinw / (2.0 * Q)
    a0 = 1.0 + alpha
    b0, b1, b2 = 1.0 / a0, (-2.0 * cosw) / a0, 1.0 / a0
    a1, a2 = (-2.0 * cosw) / a0, (1.0 - alpha) / a0

    flat = x.ndim == 1
    sig = x[:, None] if flat else x
    y = np.empty_like(sig)
    x1 = np.zeros(sig.shape[1]); x2 = np.zeros(sig.shape[1])
    y1 = np.zeros(sig.shape[1]); y2 = np.zeros(sig.shape[1])
    for n in range(sig.shape[0]):
        xn = sig[n]
        yn = b0 * xn + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        y[n] = yn
        x2, x1 = x1, xn
        y2, y1 = y1, yn
    return y[:, 0] if flat else y


def eeg_headset_status(buf: np.ndarray, fs: float, *, threshold: float = 100.0,
                       line_freq: float = 60.0, Q: float = 10.0) -> tuple[int, list[int]]:
    """Reproduce ``EEGHeadsetDetection`` per-channel + overall.

    ``buf`` is samples × channels (already AUX-stripped by the caller). Returns
    ``(overall, per_channel)`` where each code is 1 (bad) or 2 (good). The overall is 1 if
    ANY channel is bad — matching goofi's max-over-all-channels logic. Disconnected (0) is a
    no-data state owned by the adapter, not derivable from a populated buffer."""
    buf = np.asarray(buf, dtype=np.float64)
    if buf.ndim == 1:
        buf = buf[:, None]
    if buf.shape[0] < 2 or buf.shape[1] == 0:
        return HSI_DISCONNECTED, [HSI_DISCONNECTED] * (buf.shape[1] if buf.ndim == 2 else 0)
    x = buf - buf.mean(axis=0)                 # Filter: demean
    x = notch_filter(x, fs, line_freq, Q)      # Filter: notch 60 Hz
    centred_abs = np.abs(x - x.mean(axis=0))   # EEGHeadsetDetection: centre + |.|
    per_ch_max = centred_abs.max(axis=0)
    per_ch = np.where(per_ch_max > threshold, HSI_BAD, HSI_GOOD).astype(int).tolist()
    overall = HSI_BAD if any(c == HSI_BAD for c in per_ch) else HSI_GOOD
    return overall, per_ch


def pan_tompkins_peaks(x: np.ndarray, fs: float) -> np.ndarray:
    """Numpy Pan–Tompkins R-peak detection. Returns peak sample indices (into ``x``).

    Pipeline: derivative → square → moving-window integration → dynamic threshold with a
    physiological refractory period, then each integration lobe is refined to the local
    maximum of the raw signal (the actual R-peak). Returns an empty array for short input."""
    x = np.asarray(x, dtype=np.float64).ravel()
    if fs <= 0 or x.size < int(0.5 * fs) + 2:
        return np.empty(0, dtype=int)

    deriv = np.ediff1d(x, to_begin=0.0)
    squared = deriv ** 2
    win = max(1, int(round(0.150 * fs)))                    # ~150 ms QRS window
    integ = np.convolve(squared, np.ones(win) / win, mode="same")
    if integ.max() <= 0:
        return np.empty(0, dtype=int)

    refractory = int(round(0.25 * fs))                       # ~240 bpm ceiling
    refine = max(1, int(round(0.05 * fs)))                   # R-peak search radius

    # Separate QRS lobes from baseline noise with a floor at a multiple of the MEDIAN of the
    # integration signal: the median sits in the (dominant) between-beat baseline, so it's
    # robust both to noise and to a single huge transient (electrode pop) — unlike a mean- or
    # max-based threshold, which one artifact would inflate enough to swamp every real QRS.
    floor = 4.0 * float(np.median(integ))
    above = integ > floor
    lobes: list[tuple[int, float]] = []                      # (peak index, peak height)
    i, n = 0, integ.size
    while i < n:
        if above[i]:
            j = i
            while j < n and above[j]:
                j += 1
            local = i + int(np.argmax(integ[i:j]))
            lobes.append((local, float(integ[local])))
            i = j
        else:
            i += 1
    if not lobes:
        return np.empty(0, dtype=int)

    thr = 0.3 * float(np.median([h for _, h in lobes]))
    peaks: list[int] = []
    for local, height in lobes:
        if height < thr:
            continue
        lo = max(0, local - refine); hi = min(n, local + refine + 1)
        r = lo + int(np.argmax(x[lo:hi]))                    # refine to the raw R-peak
        if not peaks or (r - peaks[-1]) >= refractory:
            peaks.append(r)
        elif x[r] > x[peaks[-1]]:                            # keep the taller of two close peaks
            peaks[-1] = r
    return np.asarray(peaks, dtype=int)


def hrv_metrics(peaks: np.ndarray, fs: float) -> dict:
    """Time-domain HRV from R-peak indices. Returns BPM + SDNN/SDSD/RMSSD (ms) and the
    beat count. All-None (with n_beats) when there aren't enough beats."""
    peaks = np.asarray(peaks, dtype=float).ravel()
    none = {"bpm": None, "sdnn": None, "sdsd": None, "rmssd": None, "n_beats": int(peaks.size)}
    if peaks.size < 2 or fs <= 0:
        return none
    rr_all = np.diff(peaks) / fs * 1000.0                     # all NN intervals, ms
    valid = (rr_all > 250.0) & (rr_all < 2500.0)             # physiologic 24–240 bpm
    med = float(np.median(rr_all))
    if med > 0:
        # also drop intervals that span a missed beat (~2× median) or a spurious extra beat
        valid &= (rr_all > 0.5 * med) & (rr_all < 1.5 * med)
    rr = rr_all[valid]
    if rr.size < 1:
        return none
    bpm = float(60000.0 / np.mean(rr))
    sdnn = float(np.std(rr, ddof=1)) if rr.size > 1 else 0.0
    # successive differences only between ADJACENT valid intervals — a dropped/rejected interval
    # must not create a phantom large jump between the intervals that bracketed the gap.
    adj = valid[:-1] & valid[1:]
    drr = np.diff(rr_all)[adj]
    sdsd = float(np.std(drr, ddof=1)) if drr.size > 1 else 0.0
    rmssd = float(np.sqrt(np.mean(drr ** 2))) if drr.size > 0 else 0.0
    return {"bpm": round(bpm, 1), "sdnn": round(sdnn, 1), "sdsd": round(sdsd, 1),
            "rmssd": round(rmssd, 1), "n_beats": int(peaks.size)}
