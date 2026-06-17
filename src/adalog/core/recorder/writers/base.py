"""StreamWriter base + registry + shared helpers.

A writer is the ONLY component that touches a stream's on-disk bytes. It persists
payloads keyed by *session seconds* (the Core has already mapped device time → session
time), tracks counts for reconcile, and knows how to repair its own torn tail after a
crash. Writers are clock-free and goofi-free.
"""
from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Sequence

from ...manifest import Confidence, FileEntry, Timing
from ...spec import StreamSpec

WRITER_REGISTRY: dict[str, type["StreamWriter"]] = {}


def register_writer(encoding: str):
    def deco(cls: type["StreamWriter"]) -> type["StreamWriter"]:
        cls.encoding = encoding
        WRITER_REGISTRY[encoding] = cls
        return cls

    return deco


def get_writer(encoding: str) -> type["StreamWriter"]:
    try:
        return WRITER_REGISTRY[encoding]
    except KeyError:
        raise KeyError(f"no StreamWriter registered for encoding {encoding!r}; have {sorted(WRITER_REGISTRY)}")


def derive_confidence(mode: str, provenance: str) -> Confidence:
    """One coherent uncertainty rollup from timing mode + clock provenance (spec §4.3)."""
    if provenance == "reconstructed":
        return "approximate"
    if provenance in ("nominal", "host_arrival"):
        return "nominal"
    if mode == "per_sample" and provenance in ("device_lsl", "device_portaudio", "browser"):
        return "exact"
    if mode in ("anchored", "anchored_irregular") and provenance in ("device_lsl", "device_portaudio"):
        return "measured"
    return "measured"


def fsync_path(path: Path) -> None:
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def append_ndjson(fh, obj: dict) -> None:
    fh.write(json.dumps(obj, separators=(",", ":")).encode("utf-8"))
    fh.write(b"\n")


class StreamWriter(ABC):
    """Persist one stream to disk. Subclasses set ``encoding`` via @register_writer."""

    encoding: str = "base"

    def __init__(self, path: Path, spec: StreamSpec, *, provenance: str = "host_arrival", wall_uncertainty_s: float = 0.05):
        self.path = Path(path)
        self.spec = spec
        self.provenance = provenance
        self.wall_uncertainty_s = wall_uncertainty_s
        self.n_samples = 0
        self.seq_last = -1

    @abstractmethod
    def open(self) -> None:
        """Create the file(s) and durably write any header (fsync before first write)."""

    @abstractmethod
    def write(self, payload, ts_s: Optional[Sequence[float]], seq: int) -> int:
        """Persist a payload. ``ts_s`` = per-sample session seconds (len == n_samples) or None
        for anchored. Returns the number of samples/records written."""

    @abstractmethod
    def flush(self) -> None:
        ...

    @abstractmethod
    def close(self) -> list[FileEntry]:
        """Finalize, compute hashes + timing, return the FileEntry list for this stream."""

    @classmethod
    @abstractmethod
    def recover(cls, path: Path, spec: StreamSpec, *, provenance: str = "host_arrival",
                wall_uncertainty_s: float = 0.05) -> list[FileEntry]:
        """Salvage a torn-tail file from a crash and return its FileEntry list."""

    # ---- shared timing helpers ----
    def _confidence(self) -> Confidence:
        return derive_confidence(self.spec.timing_mode, self.provenance)
