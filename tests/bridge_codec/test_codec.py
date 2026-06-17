"""Round-trip tests for the vendored GOOF v2 codec + adalog envelope."""
from __future__ import annotations

import struct

import numpy as np
import pytest

from adalog.bridge_codec import (
    ARRAY,
    GOOF_VERSION,
    STRING,
    TABLE,
    Data,
    decode,
    decode_frame,
    encode,
    encode_frame,
)


def test_goof_version_is_2():
    assert GOOF_VERSION == 2


def test_roundtrip_array_float32_2d():
    arr = np.arange(12, dtype=np.float32).reshape(3, 4)
    data = Data(dtype=ARRAY, value=arr, meta={"units": "uV"})

    out = decode(encode(data))

    assert out.dtype == ARRAY
    assert out.meta == {"units": "uV"}
    assert out.value.dtype == np.float32
    assert out.value.shape == (3, 4)
    assert np.array_equal(out.value, arr)


def test_roundtrip_string():
    data = Data(dtype=STRING, value="hello, GOOF µV", meta={"k": 1})

    out = decode(encode(data))

    assert out.dtype == STRING
    assert out.value == "hello, GOOF µV"
    assert out.meta == {"k": 1}


def test_roundtrip_table_with_array_and_string():
    arr = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)
    table = Data(
        dtype=TABLE,
        value={
            "signal": Data(dtype=ARRAY, value=arr, meta={"sfreq": 256}),
            "label": Data(dtype=STRING, value="eeg", meta={}),
        },
        meta={"source": "test"},
    )

    out = decode(encode(table))

    assert out.dtype == TABLE
    assert out.meta == {"source": "test"}
    assert set(out.value.keys()) == {"signal", "label"}

    sig = out.value["signal"]
    assert sig.dtype == ARRAY
    assert sig.value.dtype == np.float32
    assert sig.value.shape == (2, 2)
    assert np.array_equal(sig.value, arr)
    assert sig.meta == {"sfreq": 256}

    lab = out.value["label"]
    assert lab.dtype == STRING
    assert lab.value == "eeg"


def test_decode_rejects_bad_version():
    arr = np.zeros((2, 2), dtype=np.float32)
    buf = bytearray(encode(Data(dtype=ARRAY, value=arr, meta={})))
    # The version byte sits right after the 4-byte magic.
    buf[4] = 3
    with pytest.raises(ValueError):
        decode(bytes(buf))


def test_decode_rejects_bad_magic():
    arr = np.zeros((2, 2), dtype=np.float32)
    buf = bytearray(encode(Data(dtype=ARRAY, value=arr, meta={})))
    buf[0:4] = b"XXXX"
    with pytest.raises(ValueError):
        decode(bytes(buf))


def test_big_endian_array_rejected():
    arr = np.arange(4, dtype=">f4").reshape(2, 2)
    with pytest.raises(ValueError):
        encode(Data(dtype=ARRAY, value=arr, meta={}))


def test_roundtrip_envelope_frame():
    arr = np.linspace(0.0, 1.0, 8, dtype=np.float32).reshape(2, 4)
    data = Data(dtype=ARRAY, value=arr, meta={"units": "uV"})
    header = {
        "node_id": "node-a",
        "slot_id": "out",
        "stream_id": "eeg",
        "seq": 42,
        "t": 12.5,
        "device_ts_ns": 123456789,
        "timing_mode": "anchored",
    }

    hdr_out, data_out = decode_frame(encode_frame(header, data))

    assert hdr_out == header
    assert data_out.dtype == ARRAY
    assert data_out.value.shape == (2, 4)
    assert data_out.value.dtype == np.float32
    assert np.array_equal(data_out.value, arr)


def test_envelope_frame_with_none_device_ts():
    data = Data(dtype=STRING, value="marker", meta={})
    header = {
        "node_id": "n",
        "slot_id": "s",
        "stream_id": "events",
        "seq": 0,
        "t": 0.0,
        "device_ts_ns": None,
        "timing_mode": "event",
    }

    hdr_out, data_out = decode_frame(encode_frame(header, data))

    assert hdr_out["device_ts_ns"] is None
    assert data_out.value == "marker"


def test_envelope_length_prefix_is_big_endian():
    data = Data(dtype=STRING, value="x", meta={})
    header = {"node_id": "n", "slot_id": "s", "stream_id": "z",
              "seq": 1, "t": 0.0, "device_ts_ns": None, "timing_mode": "event"}
    frame = encode_frame(header, data)
    (hdr_len,) = struct.unpack_from(">I", frame, 0)
    assert hdr_len > 0
    assert len(frame) >= 4 + hdr_len
