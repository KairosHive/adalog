"""Bounded buffers + the per-stream lossless pipe (invariant #3).

Guarantee, uniformly across all back-pressure regimes: **lossless until a bounded
buffer overflows, after which losses are COUNTED and recorded — never silent, never
unbounded (OOM)**.

- SPILL (realtime callbacks: audio/MIDI/OSC): the producer never blocks. It pushes into
  a bounded in-memory ring; on overflow it spills to a bounded on-disk WAL; only if the
  WAL is also full does it count a drop. A writer thread drains ring then WAL.
- BACKPRESSURE (pull loops: LSL/serial): the producer blocks on a full ring (slows the
  pull loop). Device-buffer overflow is detected upstream via seq arithmetic and recorded
  as a counted gap (not by this pipe).
- BLOCK (low-rate poll APIs: meteo): the producer blocks; overflow is effectively impossible.
"""
from __future__ import annotations

import pickle
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..spec import BP_BLOCK, BP_SPILL


@dataclass
class DropRange:
    from_seq: int
    to_seq: int
    count: int
    from_t: float = 0.0
    to_t: float = 0.0
    reason: str = "handoff_overflow"


class BoundedRing:
    """Thread-safe bounded FIFO. ``push`` is non-blocking; ``push_blocking`` waits."""

    def __init__(self, capacity: int):
        self.capacity = capacity
        self._dq: deque = deque()
        self._lock = threading.Lock()
        self._not_full = threading.Condition(self._lock)
        self._not_empty = threading.Condition(self._lock)
        self._closed = False

    def push(self, item) -> bool:
        with self._lock:
            if len(self._dq) >= self.capacity:
                return False
            self._dq.append(item)
            self._not_empty.notify()
            return True

    def push_blocking(self, item, timeout: Optional[float] = None) -> bool:
        with self._not_full:
            if not self._not_full.wait_for(lambda: len(self._dq) < self.capacity or self._closed, timeout):
                return False
            if self._closed:
                return False
            self._dq.append(item)
            self._not_empty.notify()
            return True

    def pop(self, timeout: Optional[float] = None):
        with self._not_empty:
            if not self._not_empty.wait_for(lambda: len(self._dq) > 0 or self._closed, timeout):
                return None
            if self._dq:
                item = self._dq.popleft()
                self._not_full.notify()
                return item
            return None

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._not_empty.notify_all()
            self._not_full.notify_all()

    @property
    def is_closed(self) -> bool:
        with self._lock:
            return self._closed

    def __len__(self) -> int:
        with self._lock:
            return len(self._dq)


class WalRing:
    """Bounded append-only on-disk spill (transient; pickled frames)."""

    def __init__(self, path: Path, max_bytes: int):
        self.path = Path(path)
        self.max_bytes = max_bytes
        self._fh = None
        self._bytes = 0

    def open(self) -> None:
        self._fh = open(self.path, "wb")

    def append(self, item) -> bool:
        blob = pickle.dumps(item, protocol=pickle.HIGHEST_PROTOCOL)
        if self._bytes + len(blob) + 4 > self.max_bytes:
            return False
        self._fh.write(len(blob).to_bytes(4, "big"))
        self._fh.write(blob)
        self._fh.flush()
        self._bytes += len(blob) + 4
        return True

    def drain(self):
        """Yield all spilled frames, then reset the WAL."""
        if self._fh:
            self._fh.flush()
        if not self.path.exists():
            return
        with open(self.path, "rb") as fh:
            while True:
                hdr = fh.read(4)
                if len(hdr) < 4:
                    break
                n = int.from_bytes(hdr, "big")
                body = fh.read(n)
                if len(body) < n:
                    break  # torn tail of WAL — stop
                yield pickle.loads(body)
        # reset
        if self._fh:
            self._fh.seek(0)
            self._fh.truncate(0)
        self._bytes = 0

    def close(self) -> None:
        if self._fh:
            self._fh.close()
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

    def __len__(self) -> int:
        return self._bytes


@dataclass
class _Item:
    payload: object
    ts_s: object
    seq: int
    n_samples: int
    t0: float


_STOP = object()


class StreamPipe:
    """One stream's bounded, regime-aware, lossless pipe + writer thread."""

    def __init__(self, writer, *, regime: str, capacity: int = 256,
                 wal_path: Optional[Path] = None, wal_max_bytes: int = 256 * 1024 * 1024):
        self.writer = writer
        self.regime = regime
        self.ring = BoundedRing(capacity)
        self.wal = WalRing(wal_path, wal_max_bytes) if (regime == BP_SPILL and wal_path) else None
        self.drops: list[DropRange] = []
        self._thread: Optional[threading.Thread] = None
        self._produced = 0
        self._persisted = 0
        self._pending_drop: Optional[DropRange] = None

    # ---- producer side ----
    def submit(self, item: _Item) -> None:
        self._produced += item.n_samples
        if self.regime == BP_SPILL:
            if self.ring.push(item):
                return
            if self.wal is not None and self.wal.append(item):
                return
            self._count_drop(item)
        elif self.regime == BP_BLOCK:
            self.ring.push_blocking(item)
        else:  # BACKPRESSURE
            self.ring.push_blocking(item)

    def _count_drop(self, item: _Item) -> None:
        if self._pending_drop and self._pending_drop.to_seq == item.seq - 1:
            self._pending_drop.to_seq = item.seq
            self._pending_drop.count += item.n_samples
            self._pending_drop.to_t = item.t0
        else:
            if self._pending_drop:
                self.drops.append(self._pending_drop)
            self._pending_drop = DropRange(from_seq=item.seq, to_seq=item.seq, count=item.n_samples,
                                           from_t=item.t0, to_t=item.t0)

    # ---- consumer thread ----
    def start(self) -> None:
        if self.wal is not None:
            self.wal.open()
        self._thread = threading.Thread(target=self._run, name=f"writer-{self.writer.spec.id}", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while True:
            item = self.ring.pop(timeout=0.1)
            if item is _STOP:
                break
            if item is None:
                self._drain_wal()
                if self.ring.is_closed:  # crash/abrupt close: stop the loop (don't spin)
                    break
                continue
            self._write(item)
            self._drain_wal()

    def _drain_wal(self) -> None:
        if self.wal is None or len(self.wal) == 0:
            return
        for item in self.wal.drain():
            self._write(item)

    def _write(self, item: _Item) -> None:
        self.writer.write(item.payload, item.ts_s, item.seq)
        self._persisted += item.n_samples

    # ---- shutdown ----
    def stop(self) -> tuple[list, dict]:
        self.ring.push_blocking(_STOP)
        if self._thread:
            self._thread.join()
        self._drain_wal()
        if self._pending_drop:
            self.drops.append(self._pending_drop)
            self._pending_drop = None
        if self.wal is not None:
            self.wal.close()
        files = self.writer.close()
        counts = {"produced": self._produced, "persisted": self._persisted}
        return files, counts
