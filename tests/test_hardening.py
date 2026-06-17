"""Phase 7 hardening: lossless stress under concurrent load + cold-boot import budget."""
import importlib
import sys
import threading
import time

import numpy as np

from adalog.core.clock import SessionClock
from adalog.core.envelope import StreamPacket
from adalog.core.reader import read_session
from adalog.core.session import Session
from adalog.core.spec import (
    TIMING_ANCHORED,
    TIMING_ANCHORED_IRREGULAR,
    TIMING_PER_SAMPLE,
    BP_BLOCK,
    BP_SPILL,
    Channel,
    StreamSpec,
)


def test_concurrent_lossless_stress(tmp_path):
    """48kHz-style audio + 256Hz EEG + bursty OSC concurrently; assert zero UNCOUNTED loss."""
    clock = SessionClock()
    s = Session.create(tmp_path / "sessions", user="stress",
                       session_id="01STRESS00000000000000000", clock=clock)

    eeg = StreamSpec(id="eeg", modality="eeg", encoding="arrow_ipc_stream",
                     timing_mode=TIMING_ANCHORED_IRREGULAR, sfreq_nominal=256.0,
                     channels=[Channel(c, "uV", "float32") for c in ("TP9", "AF7", "AF8", "TP10")])
    audio = StreamSpec(id="audio", modality="audio", encoding="wav", timing_mode=TIMING_ANCHORED,
                       sfreq_nominal=48000.0, channels=[Channel("mono")], back_pressure=BP_SPILL)
    osc = StreamSpec(id="osc", modality="osc", encoding="jsonl", timing_mode=TIMING_PER_SAMPLE,
                     back_pressure=BP_SPILL)
    s.arm([eeg, audio, osc])
    s.start()

    produced = {"eeg": 0, "audio": 0, "osc": 0}

    def feed_eeg():
        step = int(1e9 / 256)
        for c in range(200):  # 200 chunks * 4 = 800 samples
            mono = clock.now_mono_ns()
            ts = [mono + i * step for i in range(4)]
            s.ingest(StreamPacket(stream_id="eeg", seq=c, payload=np.random.rand(4, 4).astype(np.float32),
                                  n_samples=4, device_ts_ns=ts[0], recv_mono_ns=mono, per_sample_ts=ts))
            produced["eeg"] += 4

    def feed_audio():
        for c in range(300):  # 300 blocks * 512 = 153600 frames
            mono = clock.now_mono_ns()
            s.ingest(StreamPacket(stream_id="audio", seq=c, payload=np.random.rand(512).astype(np.float32),
                                  n_samples=512, device_ts_ns=mono, recv_mono_ns=mono))
            produced["audio"] += 512

    def feed_osc():
        for c in range(500):
            s.ingest(StreamPacket(stream_id="osc", seq=c, payload={"address": "/x", "value": c},
                                  device_ts_ns=clock.now_mono_ns()))
            produced["osc"] += 1

    threads = [threading.Thread(target=f) for f in (feed_eeg, feed_audio, feed_osc)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    time.sleep(0.3)
    manifest = s.stop()

    rs = read_session(s.dir / "manifest.json")
    # every produced sample is either persisted or COUNTED as a drop (never silently lost)
    for sid in ("eeg", "audio", "osc"):
        st = rs.stream(sid)
        n = st.array.shape[0] if st.array is not None else len(st.records or [])
        drops = sum(d.count for d in (st.timing.drops if st.timing else []))
        assert n + drops == produced[sid], f"{sid}: persisted {n} + drops {drops} != produced {produced[sid]}"
        # under this moderate load with default buffers, expect fully lossless
        assert drops == 0, f"{sid}: unexpected drops {drops}"


def test_cold_boot_import_budget():
    """The standalone hot path must not pull heavy device/ML libs at import time."""
    heavy = {"torch", "pylsl", "sounddevice", "mido", "mediapipe", "transformers", "goofi", "iceoryx2", "serial"}
    for mod in list(sys.modules):
        top = mod.split(".")[0]
        if top in heavy:
            del sys.modules[mod]
    # importing the service + bridge must not import any heavy lib
    importlib.import_module("adalog.sense.service")
    importlib.import_module("adalog.sense.bridge.server")
    leaked = heavy & {m.split(".")[0] for m in sys.modules}
    assert not leaked, f"heavy libs imported on the hot path: {leaked}"
