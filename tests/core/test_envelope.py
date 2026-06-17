import numpy as np
import pytest

from adalog.core.envelope import PacketContractError, StreamPacket, validate_packet
from adalog.core.spec import (
    TIMING_ANCHORED,
    TIMING_ANCHORED_IRREGULAR,
    TIMING_PER_SAMPLE,
    Channel,
    StreamSpec,
)


def test_streamspec_defaults():
    s = StreamSpec(id="osc", modality="osc")
    assert s.encoding == "arrow_ipc_stream"
    assert s.timing_mode == TIMING_PER_SAMPLE
    assert s.channel_names == []


def test_streamspec_rejects_unknown_mode():
    with pytest.raises(ValueError):
        StreamSpec(id="x", modality="x", timing_mode="bogus")


def test_streamspec_anchored_requires_sfreq():
    with pytest.raises(ValueError):
        StreamSpec(id="eeg", modality="eeg", timing_mode=TIMING_ANCHORED)
    ok = StreamSpec(id="eeg", modality="eeg", timing_mode=TIMING_ANCHORED, sfreq_nominal=256.0,
                    channels=[Channel("TP9", "uV")])
    assert ok.channel_names == ["TP9"]


def test_anchored_irregular_packet_requires_per_sample_ts():
    chunk = np.zeros((4, 4), dtype=np.float32)
    bad = StreamPacket(stream_id="eeg", seq=0, payload=chunk, n_samples=4)
    with pytest.raises(PacketContractError):
        validate_packet(bad, TIMING_ANCHORED_IRREGULAR)
    good = StreamPacket(stream_id="eeg", seq=0, payload=chunk, n_samples=4,
                        per_sample_ts=[1, 2, 3, 4], device_ts_ns=1)
    validate_packet(good, TIMING_ANCHORED_IRREGULAR)  # no raise


def test_per_sample_ts_length_must_match():
    chunk = np.zeros((3, 2), dtype=np.float32)
    bad = StreamPacket(stream_id="eeg", seq=1, payload=chunk, n_samples=3, per_sample_ts=[1, 2])
    with pytest.raises(PacketContractError):
        validate_packet(bad, TIMING_ANCHORED_IRREGULAR)
