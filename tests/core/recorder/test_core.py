import numpy as np

from adalog.core.clock import SessionClock
from adalog.core.envelope import StreamPacket
from adalog.core.manifest import (
    ClockAnchorModel,
    ClockBlock,
    Manifest,
    reconcile,
)
from adalog.core.reader import read_session
from adalog.core.recorder.core import RecordingCore
from adalog.core.spec import (
    TIMING_ANCHORED_IRREGULAR,
    TIMING_PER_SAMPLE,
    Channel,
    StreamSpec,
)


def _clock(fake):
    return SessionClock(mono_fn=fake.monotonic_ns, utc_fn=fake.utc_ns)


def _write_manifest(session_dir, clock, entries):
    m = Manifest(
        session_id="01CORETEST0000000000000000",
        status="complete",
        clock=ClockBlock(
            t0_anchor=ClockAnchorModel(t=0.0, mono_ns=clock.t0_mono_ns, utc_ns=clock.t0_utc_ns),
            boottime_used=clock.boottime_used, host_drift_ppm=clock.host_drift_ppm,
        ),
        streams=entries,
    )
    (session_dir / "manifest.json").write_text(m.to_json(), encoding="utf-8")
    return m


def test_end_to_end_record_and_read(fake_clock, session_dir):
    clock = _clock(fake_clock)
    core = RecordingCore(session_dir, clock)
    eeg = StreamSpec(id="eeg", modality="eeg", encoding="arrow_ipc_stream",
                     timing_mode=TIMING_ANCHORED_IRREGULAR, sfreq_nominal=256.0,
                     channels=[Channel(c, "uV", "float32") for c in ("TP9", "AF7", "AF8", "TP10")])
    text = StreamSpec(id="text", modality="text", encoding="jsonl", timing_mode=TIMING_PER_SAMPLE)
    core.add_stream(eeg, provenance="device_lsl")
    core.add_stream(text, provenance="browser")

    received = []
    core.monitor_tap("eeg", lambda p: received.append(p.seq))

    step = int(1e9 / 256)  # ns per sample @256Hz
    sample_idx = 0
    for chunk in range(4):
        mono0 = clock.now_mono_ns()
        per_sample_ts = [mono0 + i * step for i in range(4)]
        data = np.arange(16, dtype=np.float32).reshape(4, 4) + chunk
        core.ingest(StreamPacket(stream_id="eeg", seq=chunk, payload=data, n_samples=4,
                                 device_ts_ns=per_sample_ts[0], recv_mono_ns=mono0,
                                 per_sample_ts=per_sample_ts))
        sample_idx += 4
        fake_clock.tick(4 * step)  # advance one chunk

    # a couple of words
    core.ingest(StreamPacket(stream_id="text", seq=0, payload={"word": "hello"},
                             device_ts_ns=clock.now_mono_ns(), recv_mono_ns=clock.now_mono_ns()))
    fake_clock.tick(500_000_000)
    core.ingest(StreamPacket(stream_id="text", seq=1, payload={"word": "world"},
                             device_ts_ns=clock.now_mono_ns(), recv_mono_ns=clock.now_mono_ns()))

    entries = core.finalize()
    counts = core.counts()
    # lossless: produced == persisted for every stream
    for sid, c in counts.items():
        assert c["produced"] == c["persisted"], sid
    m = _write_manifest(session_dir, clock, entries)
    res = reconcile(m, counts)
    assert all(r.ok for r in res)

    # monitor plane saw the eeg packets
    assert received == [0, 1, 2, 3]

    # read back
    rs = read_session(session_dir / "manifest.json")
    eeg_s = rs.stream("eeg")
    assert eeg_s.array.shape == (16, 4)
    assert eeg_s.channels == ["TP9", "AF7", "AF8", "TP10"]
    assert eeg_s.t.shape == (16,)
    # session times monotonic and ~256Hz
    assert np.all(np.diff(eeg_s.t) > 0)
    assert abs(eeg_s.timing.sfreq_effective - 256.0) < 1.0
    assert eeg_s.timing.clock_provenance == "device_lsl"
    assert eeg_s.timing.confidence == "measured"

    text_s = rs.stream("text")
    assert [r["word"] for r in text_s.records] == ["hello", "world"]

    # eeg2txt-style epoch resolves exactly
    t0 = eeg_s.timing.t_start
    sf = eeg_s.timing.sfreq_effective
    idx = round((eeg_s.t[5] - t0) * sf)
    assert idx == 5


def test_unknown_stream_raises(fake_clock, session_dir):
    core = RecordingCore(session_dir, _clock(fake_clock))
    try:
        core.ingest(StreamPacket(stream_id="ghost", seq=0, payload={}))
        assert False, "should raise"
    except KeyError:
        pass
