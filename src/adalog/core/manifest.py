"""The manifest — THE contract (spec §4). Versioned pydantic v2 models + validate/reconcile.

The manifest is the single source of truth for a session: directory layout, per-stream
natural-format files, and honest per-file timing/provenance. Downstream (reader, inspector,
converter, ML, and Spec 2 sync) consumes only this — never raw filenames or column order.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

MANIFEST_VERSION = "1.0"

SessionStatus = Literal["recording", "complete", "recovered", "aborted"]
StreamStatus = Literal["complete", "degraded", "failed"]
TimingMode = Literal["per_sample", "anchored", "anchored_irregular", "event"]
Confidence = Literal["exact", "measured", "approximate", "nominal"]
ClockProvenance = Literal[
    "device_lsl", "device_portaudio", "browser", "host_arrival", "nominal", "reconstructed"
]


class Gap(BaseModel):
    index: int
    t: float
    duration_s: float
    reason: str = "unknown"


class Drop(BaseModel):
    from_seq: int
    to_seq: int
    from_t: float
    to_t: float
    count: int
    reason: str = "handoff_overflow"


class Timing(BaseModel):
    mode: TimingMode
    # author-declared
    sfreq_nominal: Optional[float] = None
    # core-reconstructed
    sfreq_effective: Optional[float] = None
    t_start: Optional[float] = None
    n_samples: Optional[int] = None
    index_to_t: Optional[Literal["sidecar", "uniform"]] = None
    gaps: list[Gap] = Field(default_factory=list)
    clock_provenance: Optional[ClockProvenance] = None
    confidence: Optional[Confidence] = None
    wall_uncertainty_s: Optional[float] = None
    drops: list[Drop] = Field(default_factory=list)


class FileEntry(BaseModel):
    role: str
    path: str
    encoding: str
    blake3: Optional[str] = None
    bytes: Optional[int] = None
    timing: Optional[Timing] = None


class AdapterRef(BaseModel):
    id: str
    version: str = "0"
    template: Optional[str] = None


class DeviceRef(BaseModel):
    name: Optional[str] = None
    model: Optional[str] = None


class StreamSchema(BaseModel):
    channels: list[str] = Field(default_factory=list)
    units: Optional[str] = None
    dtype: Optional[str] = None


class DerivationRef(BaseModel):
    source_stream: str
    method: str
    window: dict = Field(default_factory=dict)


class StreamEntry(BaseModel):
    id: str
    modality: str
    adapter: AdapterRef
    device: DeviceRef = Field(default_factory=DeviceRef)
    schema_: StreamSchema = Field(default_factory=StreamSchema, alias="schema")
    derivation: Optional[DerivationRef] = None
    files: list[FileEntry] = Field(default_factory=list)
    segments: int = 1
    status: StreamStatus = "complete"

    model_config = {"populate_by_name": True}

    def data_file(self) -> Optional[FileEntry]:
        for f in self.files:
            if f.role == "data":
                return f
        return self.files[0] if self.files else None


class ClockAnchorModel(BaseModel):
    t: float
    mono_ns: int
    utc_ns: int


class ClockBlock(BaseModel):
    source: str = "monotonic_ns"
    t0_anchor: ClockAnchorModel
    reanchors: list[ClockAnchorModel] = Field(default_factory=list)
    host_drift_ppm: float = 0.0
    boottime_used: bool = False
    wall_uncertainty_s: float = 0.05
    tz: Optional[str] = None


class Provenance(BaseModel):
    user_id: str = "u_local"
    app: str = "adalog-sense"
    app_version: str = "0"
    host: Optional[str] = None
    os: Optional[str] = None
    created_with: Literal["standalone", "goofi"] = "standalone"


class Subject(BaseModel):
    id: str = "u_local"
    attributes: dict = Field(default_factory=dict)


class Pause(BaseModel):
    from_t: float
    to_t: float


class Manifest(BaseModel):
    manifest_version: str = MANIFEST_VERSION
    session_id: str
    status: SessionStatus = "recording"
    label: str = ""
    subject: Subject = Field(default_factory=Subject)
    provenance: Provenance = Field(default_factory=Provenance)
    clock: ClockBlock
    duration_s: float = 0.0
    pauses: list[Pause] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    collection_refs: list[str] = Field(default_factory=list)
    events_file: str = "events.ndjson"
    streams: list[StreamEntry] = Field(default_factory=list)

    def to_json(self) -> str:
        return self.model_dump_json(by_alias=True, indent=2, exclude_none=False)

    @classmethod
    def from_json(cls, text: str) -> "Manifest":
        return cls.model_validate_json(text)

    def stream(self, stream_id: str) -> Optional[StreamEntry]:
        for s in self.streams:
            if s.id == stream_id:
                return s
        return None


class ReconcileResult(BaseModel):
    stream_id: str
    declared: int
    persisted: int
    produced: int
    ok: bool
    detail: str = ""


def reconcile(manifest: Manifest, counts: dict[str, dict[str, int]]) -> list[ReconcileResult]:
    """Assert produced == persisted == declared per stream.

    ``counts`` maps stream_id -> {"produced": int, "persisted": int}. ``declared`` is
    read from the stream's data-file ``timing.n_samples``. A mismatch marks the stream
    ``degraded`` (never hidden).
    """
    results: list[ReconcileResult] = []
    for stream in manifest.streams:
        df = stream.data_file()
        declared = (df.timing.n_samples if df and df.timing and df.timing.n_samples is not None else 0)
        c = counts.get(stream.id, {})
        produced = c.get("produced", declared)
        persisted = c.get("persisted", declared)
        ok = declared == persisted == produced
        if not ok:
            stream.status = "degraded"
        results.append(
            ReconcileResult(
                stream_id=stream.id, declared=declared, persisted=persisted, produced=produced,
                ok=ok, detail="" if ok else f"declared={declared} persisted={persisted} produced={produced}",
            )
        )
    return results
