"""SPILL back-pressure (audio/MIDI/OSC) must stay lossless AND in-order when the in-memory
ring overflows to the on-disk WAL — the core invariant. Regression tests for the WAL
append/drain race (silent frame loss) and the ring+WAL interleave (reordered samples)."""
import threading
import time

from adalog.core.recorder.ringbuffer import StreamPipe, _Item
from adalog.core.spec import BP_SPILL


class _Spec:
    id = "t"


class _RecordingWriter:
    """Captures the (seq) order it is asked to write; can be slow to force ring overflow."""
    spec = _Spec()

    def __init__(self, per_write_sleep: float = 0.0, first_write_sleep: float = 0.0):
        self.written: list[int] = []
        self._per = per_write_sleep
        self._first = first_write_sleep
        self._is_first = True

    def open(self):
        pass

    def write(self, payload, ts_s, seq):
        if self._is_first and self._first:
            self._is_first = False
            time.sleep(self._first)
        elif self._per:
            time.sleep(self._per)
        self.written.append(seq)

    def close(self):
        return []


def _item(seq: int) -> _Item:
    return _Item(payload=seq, ts_s=[float(seq)], seq=seq, n_samples=1, t0=float(seq))


def test_spill_is_lossless_and_ordered_under_ring_overflow(tmp_path):
    # tiny ring + a slow first write => the flood overflows the ring into the WAL
    w = _RecordingWriter(first_write_sleep=0.05)
    pipe = StreamPipe(w, regime=BP_SPILL, capacity=2,
                      wal_path=tmp_path / "t.wal", wal_max_bytes=64 * 1024 * 1024)
    pipe.start()
    for s in range(300):
        pipe.submit(_item(s))
    _files, counts = pipe.stop()

    assert counts["produced"] == 300
    assert counts["persisted"] == 300, "frames were silently lost on overflow"
    assert w.written == list(range(300)), \
        f"samples written out of order: first divergence near {next((i for i, v in enumerate(w.written) if v != i), None)}"


def test_spill_hard_wal_error_becomes_counted_drop(tmp_path):
    # a real disk write failure (not the soft size cap) must degrade to a COUNTED drop, not
    # raise out of submit() into the realtime audio callback and abort the stream.
    w = _RecordingWriter()
    pipe = StreamPipe(w, regime=BP_SPILL, capacity=1,
                      wal_path=tmp_path / "t.wal", wal_max_bytes=64 * 1024 * 1024)
    pipe.wal.open()
    def boom(_item):
        raise OSError("disk full")
    pipe.wal.append = boom   # simulate a hard write failure

    pipe.submit(_item(0))    # fills the (size-1) ring
    pipe.submit(_item(1))    # ring full -> wal.append() raises -> must be caught + counted
    assert pipe._produced == 2
    pending = pipe._pending_drop
    assert (pending is not None) or pipe.drops, "failed WAL append was not recorded as a drop"


def test_spill_no_loss_under_concurrent_drain(tmp_path):
    # writer sleeps a little on every write so draining overlaps the producer's appends,
    # exercising the append()/drain()-truncate race that silently dropped frames.
    w = _RecordingWriter(per_write_sleep=0.0005)
    pipe = StreamPipe(w, regime=BP_SPILL, capacity=4,
                      wal_path=tmp_path / "t.wal", wal_max_bytes=128 * 1024 * 1024)
    pipe.start()
    N = 2000
    for s in range(N):
        pipe.submit(_item(s))
        if s % 50 == 0:
            time.sleep(0)  # yield to the writer so drain and append interleave
    _files, counts = pipe.stop()

    assert counts["persisted"] == N, f"lost {N - counts['persisted']} frames (WAL race)"
    assert w.written == list(range(N)), "frames written out of order"
