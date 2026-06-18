"""Pre-recording preview: monitors receive live data once a device is armed; nothing is
written to disk until Record; recording then captures samples."""
import threading
import time

import numpy as np

from adalog.adapters.base import AdapterInfo, DeviceAdapter
from adalog.adapters.registry import AdapterRegistry
from adalog.core.envelope import StreamPacket
from adalog.core.reader import read_session
from adalog.core.spec import Channel, StreamSpec
from adalog.sense.service import RecorderService


class StreamingAdapter(DeviceAdapter):
    """Emits continuously (like real hardware) until stopped."""
    info = AdapterInfo(id="synthstream", title="Synth Stream", multi=True)

    def declare_streams(self):
        return [StreamSpec(id="sig", modality="test", encoding="arrow_ipc_stream",
                           timing_mode="anchored_irregular", sfreq_nominal=256.0, channels=[Channel("a")])]

    def start(self):
        self._run = True
        i = 0
        while self._run:
            mono = self.ctx.now_mono_ns()
            ts = [mono + j * 4_000_000 for j in range(4)]
            self.ctx.emit(StreamPacket(stream_id="sig", seq=i, payload=np.ones((4, 1), dtype="float32") * i,
                                       n_samples=4, device_ts_ns=ts[0], recv_mono_ns=mono, per_sample_ts=ts))
            i += 1
            time.sleep(0.005)

    def stop(self):
        self._run = False


def _svc(tmp_path):
    reg = AdapterRegistry(); reg.register(StreamingAdapter)
    return RecorderService(sessions_root=tmp_path / "s", registry=reg, include_entrypoints=False)


def test_preview_streams_to_monitor_before_recording(tmp_path):
    svc = _svc(tmp_path)
    svc.session_create(user="t")
    seen = []
    arm = svc.device_arm(adapter_id="synthstream", instance_id="0")
    # tap the monitor plane right after arm (preview), BEFORE recording
    svc.session.core.monitor_tap(arm["streams"][0]["id"], lambda p: seen.append(p.seq))
    time.sleep(0.1)
    # monitors are receiving live preview data...
    assert len(seen) > 0, "no preview data reached the monitor plane"
    # ...but nothing is written to disk yet
    counts = svc.session.core.live_counts()
    assert counts["sig"]["persisted"] == 0

    # now record -> disk path turns on
    svc.session_arm()
    svc.session_start()
    time.sleep(0.1)
    out = svc.session_stop()

    rs = read_session(out["manifest_path"])
    assert rs.stream("sig").array.shape[0] > 0, "recording captured no samples"


def test_pause_keeps_monitor_live_but_stops_disk(tmp_path):
    svc = _svc(tmp_path)
    svc.session_create(user="t")
    svc.device_arm(adapter_id="synthstream", instance_id="0")
    svc.session_arm(); svc.session_start()
    time.sleep(0.06)
    svc.session_pause()
    # capture persisted count at pause, then ensure it doesn't grow while paused
    paused_at = svc.session.core.live_counts()["sig"]["persisted"]
    time.sleep(0.08)
    still = svc.session.core.live_counts()["sig"]["persisted"]
    assert still == paused_at, "disk kept writing while paused"
    svc.session_resume()
    time.sleep(0.06)
    svc.session_stop()
    assert svc.session.core.live_counts()["sig"]["persisted"] > paused_at, "recording did not resume"
