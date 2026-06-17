"""SessionClock — the single monotonic master clock for a recording session.

Invariant #1: session time derives only from a monotonic source. Wall-clock UTC
enters as periodically re-sampled ``(mono_ns, utc_ns)`` *anchor pairs*, never per
sample. This module is the ONLY place permitted to read the wall clock.

On Linux we prefer ``CLOCK_BOOTTIME`` so a suspend counts as real elapsed time
(the data then shows a genuine gap, no synthetic clock-jump). On platforms whose
monotonic clock stops during sleep we fall back to ``CLOCK_MONOTONIC`` and detect
a suspend at the next re-anchor (recorded as an explicit clock event).

All time sources are injectable so tests are deterministic (no real sleep).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

# Threshold (seconds) above which a wall/mono divergence at re-anchor is treated
# as a suspend (only meaningful on the non-BOOTTIME fallback path).
_SUSPEND_THRESHOLD_S = 1.0


@dataclass(frozen=True)
class ClockAnchor:
    """A single ``(session_t, monotonic_ns, utc_ns)`` correspondence."""

    t: float        # session seconds since t0
    mono_ns: int    # monotonic source value
    utc_ns: int     # wall-clock UTC nanoseconds at that monotonic instant


@dataclass(frozen=True)
class SuspendEvent:
    """A detected suspend on the fallback (non-BOOTTIME) path."""

    t: float        # session seconds at which the suspend was detected
    gap_s: float    # estimated wall-clock duration of the suspend


def _default_boottime_ns() -> Optional[int]:
    clk = getattr(time, "CLOCK_BOOTTIME", None)
    if clk is None:
        return None
    return time.clock_gettime_ns(clk)


class SessionClock:
    """Monotonic-first session clock with periodic UTC anchoring + drift fit."""

    def __init__(
        self,
        *,
        mono_fn: Optional[Callable[[], int]] = None,
        utc_fn: Optional[Callable[[], int]] = None,
        boottime_fn: Optional[Callable[[], Optional[int]]] = None,
        use_boottime: bool = True,
    ) -> None:
        self._utc_fn = utc_fn or time.time_ns
        boottime_fn = boottime_fn if boottime_fn is not None else _default_boottime_ns

        if use_boottime and mono_fn is None:
            bt = boottime_fn()
            if bt is not None:
                self._mono_fn: Callable[[], int] = lambda: _coalesce(boottime_fn(), time.monotonic_ns())
                self.boottime_used = True
            else:
                self._mono_fn = time.monotonic_ns
                self.boottime_used = False
        elif mono_fn is not None:
            # Explicit injection (tests). use_boottime controls only the reported flag.
            self._mono_fn = mono_fn
            self.boottime_used = bool(use_boottime)
        else:
            self._mono_fn = time.monotonic_ns
            self.boottime_used = False

        self.t0_mono_ns: int = self._mono_fn()
        self.t0_utc_ns: int = self._utc_fn()
        self.anchors: list[ClockAnchor] = [ClockAnchor(0.0, self.t0_mono_ns, self.t0_utc_ns)]
        self.suspend_events: list[SuspendEvent] = []
        # Drift fit in coordinates RELATIVE to t0 (preserves ns precision; absolute
        # UTC ns ~1e18 exceeds float64 mantissa):
        #   utc_ns ≈ t0_utc_ns + _utc_a + _utc_b * (mono_ns - t0_mono_ns)
        self._utc_a: float = 0.0
        self._utc_b: float = 1.0

    # ---- live reads -----------------------------------------------------
    def now_mono_ns(self) -> int:
        return self._mono_fn()

    def now_s(self) -> float:
        return (self._mono_fn() - self.t0_mono_ns) / 1e9

    def mono_to_t(self, mono_ns: int) -> float:
        """Session seconds for a monotonic value (e.g. a device-mapped timestamp)."""
        return (mono_ns - self.t0_mono_ns) / 1e9

    # ---- anchoring ------------------------------------------------------
    def reanchor(self) -> ClockAnchor:
        """Sample a fresh ``(mono, utc)`` pair, refit drift, detect suspend."""
        mono = self._mono_fn()
        utc = self._utc_fn()
        t = (mono - self.t0_mono_ns) / 1e9

        prev = self.anchors[-1]
        if not self.boottime_used:
            mono_delta = (mono - prev.mono_ns) / 1e9
            utc_delta = (utc - prev.utc_ns) / 1e9
            if (utc_delta - mono_delta) > _SUSPEND_THRESHOLD_S:
                self.suspend_events.append(SuspendEvent(t=t, gap_s=utc_delta - mono_delta))

        anchor = ClockAnchor(t, mono, utc)
        self.anchors.append(anchor)
        self._refit()
        return anchor

    def _refit(self) -> None:
        n = len(self.anchors)
        if n < 2:
            return
        # Relative coordinates (see __init__): x = mono - t0_mono, y = utc - t0_utc.
        xs = [float(a.mono_ns - self.t0_mono_ns) for a in self.anchors]
        ys = [float(a.utc_ns - self.t0_utc_ns) for a in self.anchors]
        mx = sum(xs) / n
        my = sum(ys) / n
        sxx = sum((x - mx) ** 2 for x in xs)
        if sxx == 0:
            return
        sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        self._utc_b = sxy / sxx
        self._utc_a = my - self._utc_b * mx

    def mono_to_utc_ns(self, mono_ns: int) -> int:
        """Reconstruct UTC for a monotonic value via the drift fit."""
        rel = self._utc_a + self._utc_b * (mono_ns - self.t0_mono_ns)
        return self.t0_utc_ns + round(rel)

    @property
    def host_drift_ppm(self) -> float:
        return (self._utc_b - 1.0) * 1e6


def _coalesce(value: Optional[int], fallback: int) -> int:
    return fallback if value is None else value
