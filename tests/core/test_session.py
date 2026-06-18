import time

import numpy as np

from adalog.core.clock import SessionClock
from adalog.core.envelope import StreamPacket
from adalog.core.reader import read_session
from adalog.core.session import Session, needs_recovery, recover_session
from adalog.core.spec import (
    TIMING_ANCHORED_IRREGULAR,
    TIMING_PER_SAMPLE,
    Channel,
    StreamSpec,
)


def _eeg_spec():
    return StreamSpec(id="eeg", modality="eeg", encoding="arrow_ipc_stream",
                      timing_mode=TIMING_ANCHORED_IRREGULAR, sfreq_nominal=256.0,
                      channels=[Channel(c, "uV", "float32") for c in ("TP9", "AF7", "AF8", "TP10")])


def _text_spec():
    return StreamSpec(id="text", modality="text", encoding="jsonl", timing_mode=TIMING_PER_SAMPLE)


def _feed_eeg(session, clock, fake, chunks=4):
    step = int(1e9 / 256)
    for c in range(chunks):
        mono0 = clock.now_mono_ns()
        ts = [mono0 + i * step for i in range(4)]
        data = np.ones((4, 4), dtype=np.float32) * c
        session.ingest(StreamPacket(stream_id="eeg", seq=c, payload=data, n_samples=4,
                                    device_ts_ns=ts[0], recv_mono_ns=mono0, per_sample_ts=ts))
        fake.tick(4 * step)


def test_full_session_lifecycle(tmp_path, fake_clock):
    clock = SessionClock(mono_fn=fake_clock.monotonic_ns, utc_fn=fake_clock.utc_ns)
    s = Session.create(tmp_path / "sessions", user="u_test", label="hi", tags=["eeg"],
                       session_id="01SESSIONTEST0000000000000", clock=clock)
    assert needs_recovery(s.dir) is True  # lock present while recording
    s.arm([_eeg_spec(), _text_spec()])
    s.start()
    _feed_eeg(s, clock, fake_clock, chunks=4)
    s.ingest(StreamPacket(stream_id="text", seq=0, payload={"word": "hello"},
                          device_ts_ns=clock.now_mono_ns(), recv_mono_ns=clock.now_mono_ns()))
    s.pause()
    # dropped while paused
    assert s.ingest(StreamPacket(stream_id="text", seq=1, payload={"word": "nope"},
                                 device_ts_ns=clock.now_mono_ns())) is False
    fake_clock.tick(1_000_000_000)
    s.resume()
    time.sleep(0.05)
    manifest = s.stop()

    assert manifest.status == "complete"
    assert needs_recovery(s.dir) is False  # lock removed
    assert len(manifest.pauses) == 1
    rs = read_session(s.dir / "manifest.json")
    assert rs.stream("eeg").array.shape == (16, 4)
    assert [r["word"] for r in rs.stream("text").records] == ["hello"]


def test_fsm_guards(tmp_path, fake_clock):
    clock = SessionClock(mono_fn=fake_clock.monotonic_ns, utc_fn=fake_clock.utc_ns)
    s = Session.create(tmp_path / "sessions", session_id="01GUARD000000000000000000", clock=clock)
    import pytest
    with pytest.raises(RuntimeError):
        s.start()  # not armed
    s.arm([_eeg_spec()])
    with pytest.raises(RuntimeError):
        s.pause()  # not recording


def test_late_joined_stream_survives_recovery(tmp_path, fake_clock):
    # a device armed AFTER recording started (late-join) must be in the draft manifest, so a
    # crash before stop still recovers its stream instead of orphaning it.
    clock = SessionClock(mono_fn=fake_clock.monotonic_ns, utc_fn=fake_clock.utc_ns)
    s = Session.create(tmp_path / "sessions", user="u_test",
                       session_id="01LATEJOIN0000000000000000", clock=clock)
    s.arm([_eeg_spec()])
    s.start()
    s.add_stream(_text_spec())   # late join after start
    recovered = recover_session(s.dir)
    ids = {st.id for st in recovered.streams}
    assert ids == {"eeg", "text"}, f"late-joined stream lost on recovery: {ids}"


def test_crash_recovery(tmp_path, fake_clock):
    clock = SessionClock(mono_fn=fake_clock.monotonic_ns, utc_fn=fake_clock.utc_ns)
    s = Session.create(tmp_path / "sessions", user="u_test",
                       session_id="01CRASHTEST00000000000000", clock=clock)
    s.arm([_eeg_spec()])
    s.start()
    _feed_eeg(s, clock, fake_clock, chunks=5)
    time.sleep(0.1)  # let writer threads flush durably

    # simulate kill -9: stop writer threads abruptly (no EOS), corrupt the arrow tail
    sdir = s.dir
    arrow = sdir / "streams" / "eeg" / "eeg.arrow"
    for st in s.core._streams.values():
        st.pipe.ring.close()
        st.writer._sink.flush()
    time.sleep(0.05)
    size = arrow.stat().st_size
    with open(arrow, "r+b") as fh:
        fh.truncate(size - 10)  # cut into the last batch

    assert needs_recovery(sdir) is True
    recovered = recover_session(sdir)
    assert recovered.status == "recovered"
    assert needs_recovery(sdir) is False
    rs = read_session(sdir / "manifest.json")
    n = rs.stream("eeg").array.shape[0]
    assert 0 < n <= 20  # at least some complete batches salvaged, never more than produced
    assert n % 4 == 0   # whole batches only
