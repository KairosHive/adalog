"""DeviceClock — maps a device's native timestamps into the session monotonic domain.

Every adapter supplies the best native timestamps it has (LSL ``pull_chunk`` per-sample
times, PortAudio ``inputBufferAdcTime``, a browser ``performance.now()`` reconciled by a
handshake). A per-stream DeviceClock keeps a robust, continuously-updated offset+skew fit
from ``(device_ts_ns, recv_mono_ns)`` observations and maps any device timestamp to the
session monotonic domain. The fit is robust to outliers (e.g. buffer-coalesced backward
stamps) via median/MAD trimming, so a few bad stamps never corrupt the whole stream.
"""
from __future__ import annotations

from collections import deque
from statistics import median
from typing import Deque, Tuple

# Provenance labels (also used in the manifest timing.clock_provenance field).
PROV_LSL = "device_lsl"
PROV_PORTAUDIO = "device_portaudio"
PROV_BROWSER = "browser"
PROV_HOST_ARRIVAL = "host_arrival"
PROV_NOMINAL = "nominal"
PROV_RECONSTRUCTED = "reconstructed"


class DeviceClock:
    def __init__(self, provenance: str = PROV_HOST_ARRIVAL, *, window: int = 512, min_skew_samples: int = 16):
        self.provenance = provenance
        self._window = window
        self._min_skew_samples = min_skew_samples
        self._pairs: Deque[Tuple[int, int]] = deque(maxlen=window)
        self._ref: int | None = None   # first device_ts seen; fit is relative to it
        self._a: float = 0.0           # mapped session-mono at device_ts == ref
        self._b: float = 1.0           # skew d(session_mono)/d(device_ts)

    def update(self, device_ts_ns: int, recv_mono_ns: int) -> None:
        if self._ref is None:
            self._ref = device_ts_ns
            self._a = float(recv_mono_ns)  # seed: first arrival defines the offset
        self._pairs.append((device_ts_ns, recv_mono_ns))
        self._refit()

    def _refit(self) -> None:
        # Fit recv_mono ≈ a + b*(device_ts - ref), robust to outliers.
        pairs = list(self._pairs)
        ref = self._ref or 0
        xs = [float(d - ref) for d, _ in pairs]
        ys = [float(r) for _, r in pairs]

        if len(pairs) < self._min_skew_samples:
            # Offset-only (skew fixed at 1.0): a = median(recv - device_rel).
            self._b = 1.0
            self._a = median([y - x for x, y in zip(xs, ys)])
            return

        # Trim by residual MAD against the current fit, then least-squares on inliers.
        resid = [abs(y - (self._a + self._b * x)) for x, y in zip(xs, ys)]
        m = median(resid)
        mad = median([abs(r - m) for r in resid]) or 1.0
        inliers = [(x, y) for x, y, r in zip(xs, ys, resid) if abs(r - m) <= 6.0 * mad]
        if len(inliers) < self._min_skew_samples:
            inliers = list(zip(xs, ys))
        n = len(inliers)
        mx = sum(x for x, _ in inliers) / n
        my = sum(y for _, y in inliers) / n
        sxx = sum((x - mx) ** 2 for x, _ in inliers)
        if sxx > 0:
            sxy = sum((x - mx) * (y - my) for x, y in inliers)
            self._b = sxy / sxx
            self._a = my - self._b * mx

    def map(self, device_ts_ns: int) -> int:
        """Map a native device timestamp to session monotonic nanoseconds."""
        ref = self._ref or 0
        return round(self._a + self._b * (device_ts_ns - ref))

    @property
    def skew(self) -> float:
        return self._b

    @property
    def drift_ppm(self) -> float:
        return (self._b - 1.0) * 1e6
