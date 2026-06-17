"""Vendored GOOF v2 wire codec + the adalog data-plane envelope (spec §11.3).

This module re-implements the GOOF v2 framing so adalog can speak to a goofi
bridge *without* importing goofi itself (the import-linter contract forbids it).
It depends on numpy + msgpack + struct only.

GOOF v2 frame layout::

    +----------------------------------------------------------+
    | magic   "GOOF"          (4 bytes)                        |
    | version u8              (== 2)                           |
    | dtype   u8              (ARRAY=0 | STRING=1 | TABLE=2)   |
    | meta_len u32 (LE)       length of the msgpack meta blob  |
    | body_len u32 (LE)       length of the body blob          |
    +----------------------------------------------------------+
    | meta   (msgpack)                                         |
    | body   (dtype-specific)                                  |
    +----------------------------------------------------------+

GOOF carries the *payload* but has no notion of which node/slot/stream produced
it. The adalog envelope wraps a GOOF frame with that routing/timing metadata.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Any, Optional

import msgpack
import numpy as np

# ---- GOOF wire constants ----
GOOF_MAGIC = b"GOOF"
GOOF_VERSION = 2

# ---- DataType discriminants ----
ARRAY = 0
STRING = 1
TABLE = 2

# struct format for the fixed header: magic, version, dtype, meta_len, body_len
_HEADER_FMT = "<4sBBII"
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)


@dataclass
class Data:
    """A GOOF data container.

    ``value`` is interpreted per ``dtype``:

    * ``ARRAY``  -> ``np.ndarray``
    * ``STRING`` -> ``str``
    * ``TABLE``  -> ``dict[str, Data]``
    """

    dtype: int
    value: Any
    meta: dict = field(default_factory=dict)


def _encode_array_body(value: np.ndarray) -> bytes:
    """Encode an ndarray body: ndim, dtype-str, shape, raw bytes."""
    if not isinstance(value, np.ndarray):
        raise TypeError(f"ARRAY value must be a numpy.ndarray, got {type(value)!r}")

    arr = np.ascontiguousarray(value)
    byteorder = arr.dtype.byteorder
    # '=' (native) is little-endian on supported platforms; '<' and '|' are fine.
    if byteorder == ">":
        raise ValueError(
            "big-endian arrays are not supported by the GOOF codec; "
            "convert with arr.astype(arr.dtype.newbyteorder('<')) first"
        )
    if byteorder == "=" and not _native_is_little_endian():
        raise ValueError(
            "native byte order is big-endian, which is not supported by the GOOF codec"
        )

    dtype_str = arr.dtype.str  # e.g. '<f4'
    dtype_bytes = dtype_str.encode("ascii")
    if len(dtype_bytes) > 255:
        raise ValueError("dtype string too long")
    if arr.ndim > 255:
        raise ValueError("array ndim too large")

    parts = [
        struct.pack("<B", arr.ndim),
        struct.pack("<B", len(dtype_bytes)),
        dtype_bytes,
    ]
    parts.extend(struct.pack("<q", dim) for dim in arr.shape)
    parts.append(arr.tobytes(order="C"))
    return b"".join(parts)


def _native_is_little_endian() -> bool:
    return np.dtype("<i4").str == np.dtype("=i4").str


def _decode_array_body(body: bytes) -> np.ndarray:
    """Reverse of :func:`_encode_array_body`."""
    off = 0
    (ndim,) = struct.unpack_from("<B", body, off)
    off += 1
    (dtype_len,) = struct.unpack_from("<B", body, off)
    off += 1
    dtype_str = body[off : off + dtype_len].decode("ascii")
    off += dtype_len
    shape = []
    for _ in range(ndim):
        (dim,) = struct.unpack_from("<q", body, off)
        off += 8
        shape.append(dim)
    raw = body[off:]
    arr = np.frombuffer(raw, dtype=np.dtype(dtype_str))
    return arr.reshape(tuple(shape))


def _encode_table_body(value: dict) -> bytes:
    """Recursively encode children to bytes and msgpack the dict of bytes."""
    if not isinstance(value, dict):
        raise TypeError(f"TABLE value must be a dict, got {type(value)!r}")
    encoded = {}
    for key, child in value.items():
        if not isinstance(child, Data):
            raise TypeError(
                f"TABLE entry {key!r} must be a Data instance, got {type(child)!r}"
            )
        encoded[key] = encode(child)
    return msgpack.packb(encoded, use_bin_type=True)


def _decode_table_body(body: bytes) -> dict:
    raw = msgpack.unpackb(body, raw=False)
    return {key: decode(child) for key, child in raw.items()}


def encode(data: Data) -> bytes:
    """Serialize a :class:`Data` container to a GOOF v2 frame."""
    if data.dtype == ARRAY:
        body = _encode_array_body(data.value)
    elif data.dtype == STRING:
        if not isinstance(data.value, str):
            raise TypeError(f"STRING value must be str, got {type(data.value)!r}")
        body = data.value.encode("utf-8")
    elif data.dtype == TABLE:
        body = _encode_table_body(data.value)
    else:
        raise ValueError(f"unknown GOOF dtype: {data.dtype}")

    meta_blob = msgpack.packb(data.meta, use_bin_type=True)
    header = struct.pack(
        _HEADER_FMT,
        GOOF_MAGIC,
        GOOF_VERSION,
        data.dtype,
        len(meta_blob),
        len(body),
    )
    return header + meta_blob + body


def decode(buf: bytes) -> Data:
    """Parse a GOOF v2 frame back into a :class:`Data` container."""
    if len(buf) < _HEADER_SIZE:
        raise ValueError("buffer too short for GOOF header")
    magic, version, dtype, meta_len, body_len = struct.unpack_from(_HEADER_FMT, buf, 0)
    if magic != GOOF_MAGIC:
        raise ValueError(f"bad GOOF magic: {magic!r}")
    if version != GOOF_VERSION:
        raise ValueError(f"unsupported GOOF version: {version} (expected {GOOF_VERSION})")

    off = _HEADER_SIZE
    meta_blob = buf[off : off + meta_len]
    off += meta_len
    body = buf[off : off + body_len]

    meta = msgpack.unpackb(meta_blob, raw=False) if meta_len else {}

    if dtype == ARRAY:
        value: Any = _decode_array_body(body)
    elif dtype == STRING:
        value = body.decode("utf-8")
    elif dtype == TABLE:
        value = _decode_table_body(body)
    else:
        raise ValueError(f"unknown GOOF dtype: {dtype}")

    return Data(dtype=dtype, value=value, meta=meta)


# ---------------------------------------------------------------------------
# The adalog data-plane envelope (the routing/timing layer GOOF lacks).
# ---------------------------------------------------------------------------


@dataclass
class EnvelopeHeader:
    """Routing + timing metadata wrapping a GOOF payload (spec §11.3)."""

    node_id: str
    slot_id: str
    stream_id: str
    seq: int
    t: float
    device_ts_ns: Optional[int]
    timing_mode: str

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "slot_id": self.slot_id,
            "stream_id": self.stream_id,
            "seq": self.seq,
            "t": self.t,
            "device_ts_ns": self.device_ts_ns,
            "timing_mode": self.timing_mode,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "EnvelopeHeader":
        return cls(
            node_id=d["node_id"],
            slot_id=d["slot_id"],
            stream_id=d["stream_id"],
            seq=d["seq"],
            t=d["t"],
            device_ts_ns=d.get("device_ts_ns"),
            timing_mode=d["timing_mode"],
        )


def encode_frame(header_dict: dict, data: Data) -> bytes:
    """Wrap a GOOF frame with a length-prefixed msgpack envelope header.

    Layout: ``u32 (big-endian) header_len`` + ``msgpack(header_dict)`` + GOOF frame.
    """
    header_blob = msgpack.packb(header_dict, use_bin_type=True)
    prefix = struct.pack(">I", len(header_blob))
    return prefix + header_blob + encode(data)


def decode_frame(buf: bytes) -> tuple[dict, Data]:
    """Reverse of :func:`encode_frame` -> ``(header_dict, Data)``."""
    if len(buf) < 4:
        raise ValueError("buffer too short for envelope header length prefix")
    (header_len,) = struct.unpack_from(">I", buf, 0)
    off = 4
    header_blob = buf[off : off + header_len]
    off += header_len
    header_dict = msgpack.unpackb(header_blob, raw=False)
    data = decode(buf[off:])
    return header_dict, data
