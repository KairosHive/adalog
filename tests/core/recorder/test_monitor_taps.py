"""Monitor-plane taps: a disconnected data-plane subscriber must be removable so its
callback stops firing (otherwise closed sockets fire forever — a leak), and concurrent
tap/untap from one thread while another ingests must not corrupt iteration."""
import threading

from adalog.core.clock import SessionClock
from adalog.core.envelope import StreamPacket
from adalog.core.recorder.core import RecordingCore
from adalog.core.spec import ENC_JSONL, TIMING_PER_SAMPLE, StreamSpec


def _core(tmp_path):
    core = RecordingCore(tmp_path, SessionClock())
    core.add_stream(StreamSpec(id="s", modality="test", encoding=ENC_JSONL, timing_mode=TIMING_PER_SAMPLE))
    return core


def _pkt(seq):
    return StreamPacket(stream_id="s", seq=seq, payload={"v": seq}, device_ts_ns=seq)


def test_monitor_tap_can_be_removed(tmp_path):
    core = _core(tmp_path)
    seen = []
    cb = lambda p: seen.append(p.seq)
    core.monitor_tap("s", cb)
    core.ingest(_pkt(0), to_disk=False)
    assert seen == [0]
    core.monitor_untap("s", cb)
    core.ingest(_pkt(1), to_disk=False)
    assert seen == [0], "removed tap still fired (leak)"


def test_untap_unknown_is_safe(tmp_path):
    core = _core(tmp_path)
    core.monitor_untap("s", lambda p: None)        # never registered — no error
    core.monitor_untap("missing", lambda p: None)  # unknown stream — no error


def test_concurrent_tap_churn_does_not_break_ingest(tmp_path):
    core = _core(tmp_path)
    stop = threading.Event()
    errors = []

    def churn():
        cbs = [lambda p: None for _ in range(8)]
        try:
            while not stop.is_set():
                for cb in cbs:
                    core.monitor_tap("s", cb)
                for cb in cbs:
                    core.monitor_untap("s", cb)
        except Exception as e:  # pragma: no cover
            errors.append(e)

    t = threading.Thread(target=churn, daemon=True)
    t.start()
    try:
        for i in range(3000):
            core.ingest(_pkt(i), to_disk=False)   # iterates taps from this thread
    except Exception as e:  # pragma: no cover
        errors.append(e)
    finally:
        stop.set(); t.join(timeout=2)
    assert not errors, f"tap churn corrupted ingest: {errors}"
