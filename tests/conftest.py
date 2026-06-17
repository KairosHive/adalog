"""Shared pytest fixtures for the adalog test suite."""
from __future__ import annotations

import itertools
import os

import pytest

# Keep the suite hermetic: never let bridge construction shell out to pnpm.
# (The dedicated frontend-build tests manage this var themselves; the browser
# e2e builds the frontend explicitly before running.)
os.environ.setdefault("ADALOG_NO_FRONTEND_BUILD", "1")


class FakeClock:
    """Deterministic monotonic + wall clock for tests (no real time, no sleep).

    Both clocks advance only when the test calls :meth:`tick`. ``mono_ns`` and
    ``utc_ns`` advance together by default but can be skewed independently to
    simulate NTP steps, suspend, and device-clock drift.
    """

    def __init__(self, mono_start: int = 1_000_000_000, utc_start: int = 1_750_000_000_000_000_000):
        self._mono = mono_start
        self._utc = utc_start

    def monotonic_ns(self) -> int:
        return self._mono

    def boottime_ns(self) -> int:
        return self._mono

    def utc_ns(self) -> int:
        return self._utc

    def tick(self, ns: int, *, utc_ns: int | None = None) -> None:
        """Advance the monotonic clock by ``ns``; advance UTC by the same unless given."""
        self._mono += ns
        self._utc += ns if utc_ns is None else utc_ns


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def session_dir(tmp_path):
    d = tmp_path / "sessions" / "u_test" / "01TESTSESSION"
    d.mkdir(parents=True)
    return d


# Deterministic "randomness" for salted-id tests
@pytest.fixture
def seq_bytes():
    counter = itertools.count()

    def _gen(n: int) -> bytes:
        return bytes((next(counter) % 256 for _ in range(n)))

    return _gen
