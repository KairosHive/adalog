"""StreamPacket — the chunk-grained recording envelope.

This is the time/seq/provenance layer the GOOF codec lacks. Adapters emit
StreamPackets via ``ctx.emit``; the RecordingCore stamps and writes them. For
``anchored_irregular`` (and explicit ``per_sample`` arrays) the packet MUST carry
per-sample device timestamps so reconstruction never assumes uniform intra-chunk
spacing (the interpolation lie this design exists to kill).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Sequence

from .spec import TIMING_NEEDS_PER_SAMPLE_TS


@dataclass(slots=True)
class StreamPacket:
    stream_id: str
    seq: int                                  # per-stream monotonic packet counter (gap detection)
    payload: Any                              # ndarray(chunk) | dict | str | bytes | PIL.Image | mido msg
    n_samples: int = 1                        # >1 for chunked arrays, 1 for events
    device_ts_ns: Optional[int] = None        # native device time of the chunk's FIRST sample
    recv_mono_ns: Optional[int] = None        # SessionClock monotonic at Core ingest (set by Core if None)
    per_sample_ts: Optional[Sequence[int]] = None  # raw per-sample device times (required for anchored_irregular)


class PacketContractError(ValueError):
    """Raised when a packet violates the timing-mode contract."""


def validate_packet(packet: StreamPacket, timing_mode: str) -> None:
    """Enforce the per-mode packet contract. Called by the conformance suite + Core."""
    if packet.n_samples < 1:
        raise PacketContractError(f"{packet.stream_id}: n_samples must be >= 1, got {packet.n_samples}")
    if timing_mode in TIMING_NEEDS_PER_SAMPLE_TS:
        if packet.per_sample_ts is None:
            raise PacketContractError(
                f"{packet.stream_id}: timing_mode {timing_mode!r} requires per_sample_ts on every packet"
            )
        if len(packet.per_sample_ts) != packet.n_samples:
            raise PacketContractError(
                f"{packet.stream_id}: per_sample_ts length {len(packet.per_sample_ts)} != n_samples {packet.n_samples}"
            )
