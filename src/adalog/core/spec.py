"""The stream contract: ``StreamSpec`` and friends.

These live in ``adalog.core`` (not ``adalog.adapters``) because the RecordingCore —
the lowest layer — consumes them. Adapters import and produce them. Keeping them in
core preserves the layered import contract (core <- adapters <- sense).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# ---- timing modes (normative enum) ----
TIMING_PER_SAMPLE = "per_sample"
TIMING_ANCHORED = "anchored"
TIMING_ANCHORED_IRREGULAR = "anchored_irregular"
TIMING_EVENT = "event"
TIMING_MODES = frozenset({TIMING_PER_SAMPLE, TIMING_ANCHORED, TIMING_ANCHORED_IRREGULAR, TIMING_EVENT})

# Modes that require per-sample device timestamps on every StreamPacket.
TIMING_NEEDS_PER_SAMPLE_TS = frozenset({TIMING_ANCHORED_IRREGULAR})

# ---- writer encodings (keys into the writer registry) ----
ENC_ARROW = "arrow_ipc_stream"
ENC_WAV = "wav"
ENC_JSONL = "jsonl"
ENC_CSV_TS = "csv_ts"
ENC_PNG = "png"
ENC_PENTRACE = "pentrace"
ENC_MIDI = "midi"

# Back-pressure regimes (chosen by the template's transport class).
BP_SPILL = "SPILL"            # realtime callbacks: lock-free handoff + WAL spill
BP_BACKPRESSURE = "BACKPRESSURE"  # pull loops: slow the loop; counted gaps on device overflow
BP_BLOCK = "BLOCK"            # low-rate poll APIs


@dataclass(frozen=True)
class Channel:
    name: str
    units: str = ""
    dtype: str = "float32"


@dataclass(frozen=True)
class FileRole:
    """One file produced by a multi-file stream (e.g. drawing snapshot + pentrace)."""

    role: str           # "data" | "timing" | "snapshot" | ...
    encoding: str
    timing_mode: str    # a multi-file stream may mix modes per role
    filename: Optional[str] = None  # default derived from stream id + role


@dataclass(frozen=True)
class Derivation:
    """Provenance for a stream computed from another (e.g. hrv from ecg)."""

    source_stream: str
    method: str
    window: dict


@dataclass
class StreamSpec:
    """What an adapter declares it will produce. Author-declared only.

    The RecordingCore composes the manifest ``timing`` object (sfreq_effective, gaps,
    index_to_t, confidence, drops) at finalize — the author never declares those.
    """

    id: str
    modality: str
    channels: list[Channel] = field(default_factory=list)
    units: Optional[str] = None
    dtype: Optional[str] = None
    encoding: str = ENC_ARROW
    timing_mode: str = TIMING_PER_SAMPLE
    sfreq_nominal: Optional[float] = None
    roles: Optional[list[FileRole]] = None        # None => single "data" file
    dynamic: bool = False                         # runtime-registered (OSC)
    back_pressure: str = BP_BACKPRESSURE
    derivation: Optional[Derivation] = None

    def __post_init__(self) -> None:
        if self.timing_mode not in TIMING_MODES:
            raise ValueError(f"unknown timing_mode {self.timing_mode!r}; must be one of {sorted(TIMING_MODES)}")
        if self.timing_mode in (TIMING_ANCHORED, TIMING_ANCHORED_IRREGULAR) and self.sfreq_nominal is None:
            raise ValueError(f"stream {self.id!r}: timing_mode {self.timing_mode!r} requires sfreq_nominal")

    @property
    def channel_names(self) -> list[str]:
        return [c.name for c in self.channels]
