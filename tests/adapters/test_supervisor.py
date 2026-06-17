import time

from adalog.adapters.base import (
    ST_ERRORED_FATAL,
    ST_STALLED,
    AdapterInfo,
    AdapterStatus,
    DeviceAdapter,
)
from adalog.adapters.supervisor import AdapterSupervisor
from adalog.core.clock import SessionClock
from adalog.core.envelope import StreamPacket
from adalog.core.reader import read_session
from adalog.core.recorder.core import RecordingCore
from adalog.core.session import Session
from adalog.core.spec import StreamSpec


class SynthAdapter(DeviceAdapter):
    info = AdapterInfo(id="synth", title="Synth")

    def __init__(self, n=5):
        self.n = n

    def declare_streams(self):
        return [StreamSpec(id="synth", modality="test", encoding="jsonl", timing_mode="per_sample")]

    def start(self):
        for i in range(self.n):
            self.ctx.emit(StreamPacket(stream_id="synth", seq=i, payload={"i": i},
                                       device_ts_ns=self.ctx.now_mono_ns()))


class CrashAdapter(DeviceAdapter):
    info = AdapterInfo(id="crash", title="Crash")

    def declare_streams(self):
        return [StreamSpec(id="crash", modality="test", encoding="jsonl", timing_mode="per_sample")]

    def start(self):
        raise RuntimeError("boom")


class StalledAdapter(DeviceAdapter):
    info = AdapterInfo(id="stalled", title="Stalled")

    def declare_streams(self):
        return [StreamSpec(id="stalled", modality="test", encoding="jsonl", timing_mode="per_sample")]

    def start(self):
        pass  # never emits

    def status(self):
        return AdapterStatus(state=ST_STALLED, rate_est=0.0)


def _core(tmp_path, fake_clock):
    clock = SessionClock(mono_fn=fake_clock.monotonic_ns, utc_fn=fake_clock.utc_ns)
    return RecordingCore(tmp_path, clock), clock


def test_error_isolation_one_crash_does_not_stop_others(tmp_path, fake_clock):
    core, clock = _core(tmp_path, fake_clock)
    events = []
    sup = AdapterSupervisor(core, clock, on_event=lambda k, d: events.append((k, d)))
    sup.add(SynthAdapter(5), "0")
    sup.add(CrashAdapter(), "0")  # same instance id, different node_id
    sup.start_all()
    time.sleep(0.1)
    sup.stop_all()
    entries = core.finalize()
    (tmp_path / "manifest.json").write_text(_wrap(entries, clock), encoding="utf-8")

    rs = read_session(tmp_path / "manifest.json")
    # synth recorded all 5 despite crash sibling
    assert len(rs.stream("synth").records) == 5
    # crash surfaced as an event, fatal state
    assert any(k == "adapter_error" for k, _ in events)
    assert sup.managed["crash#0"].state == ST_ERRORED_FATAL


def test_stall_watchdog_emits(tmp_path, fake_clock):
    core, clock = _core(tmp_path, fake_clock)
    events = []
    sup = AdapterSupervisor(core, clock, on_event=lambda k, d: events.append((k, d)))
    sup.add(StalledAdapter(), "0")
    sup.start_all()
    sup.start_watchdog(interval=0.02)
    time.sleep(0.1)
    sup.stop_all()
    assert any(k == "adapter_error" and d.get("code") == ST_STALLED for k, d in events)


def test_late_join_and_restart_segment(tmp_path, fake_clock):
    core, clock = _core(tmp_path, fake_clock)
    sup = AdapterSupervisor(core, clock)
    m = sup.add(SynthAdapter(2), "0")
    sup.start(m)
    time.sleep(0.05)
    # restart -> bumps segment
    sup.restart(m)
    time.sleep(0.05)
    sup.stop_all()
    entries = core.finalize()
    synth = next(e for e in entries if e.id == "synth")
    assert synth.segments == 2


def _wrap(entries, clock):
    from adalog.core.manifest import ClockAnchorModel, ClockBlock, Manifest
    m = Manifest(session_id="01SUPTEST0000000000000000", status="complete",
                 clock=ClockBlock(t0_anchor=ClockAnchorModel(t=0.0, mono_ns=clock.t0_mono_ns, utc_ns=clock.t0_utc_ns)),
                 streams=entries)
    return m.to_json()
