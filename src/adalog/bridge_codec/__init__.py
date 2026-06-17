"""Vendored GOOF v2 wire codec + the adalog data-plane envelope.

Pure numpy + msgpack + struct; no goofi import (import-linter contract).
"""
from __future__ import annotations

from adalog.bridge_codec.codec import (
    ARRAY,
    GOOF_MAGIC,
    GOOF_VERSION,
    STRING,
    TABLE,
    Data,
    EnvelopeHeader,
    decode,
    decode_frame,
    encode,
    encode_frame,
)

__all__ = [
    "ARRAY",
    "STRING",
    "TABLE",
    "GOOF_MAGIC",
    "GOOF_VERSION",
    "Data",
    "EnvelopeHeader",
    "encode",
    "decode",
    "encode_frame",
    "decode_frame",
]
