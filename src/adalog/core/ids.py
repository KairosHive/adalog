"""Session ids (salted, time-sortable ULIDs) and content hashing (blake3)."""
from __future__ import annotations

import hashlib
import os
import time
from typing import Callable, Optional

import blake3

# Crockford base32 (excludes I, L, O, U)
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _encode_crockford(data: bytes) -> str:
    """Encode bytes as Crockford base32 (5 bits per char)."""
    num = int.from_bytes(data, "big")
    bits = len(data) * 8
    n_chars = (bits + 4) // 5
    out = []
    for i in range(n_chars - 1, -1, -1):
        out.append(_CROCKFORD[(num >> (i * 5)) & 0x1F])
    return "".join(out)


def new_session_id(salt: str = "", *, time_ms: Optional[int] = None, rand: Callable[[int], bytes] = os.urandom) -> str:
    """A salted ULID: 48-bit ms timestamp (sortable) + 80-bit randomness (unique).

    The 80-bit tail is salted (mixed with ``salt``) so two hosts recording in the
    same millisecond cannot collide. The 48-bit time prefix keeps ids sortable by
    creation order regardless of salt.
    """
    if time_ms is None:
        time_ms = time.time_ns() // 1_000_000
    ts = (time_ms & ((1 << 48) - 1)).to_bytes(6, "big")
    tail = bytearray(rand(10))
    if salt:
        mix = hashlib.blake2b(salt.encode("utf-8"), digest_size=10).digest()
        tail = bytearray(a ^ b for a, b in zip(tail, mix))
    return _encode_crockford(ts + bytes(tail))


def blake3_bytes(data: bytes) -> str:
    return "b3:" + blake3.blake3(data).hexdigest()


def blake3_file(path, *, chunk: int = 1 << 20) -> str:
    h = blake3.blake3()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return "b3:" + h.hexdigest()
