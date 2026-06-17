"""NDJSON writer for per_sample / event streams (text, OSC, meteo, pentrace, MIDI mirror).

Each record is one line ``{"t": <session seconds>, ...}``. Crash-safe by construction:
``recover()`` simply truncates to the last complete newline-terminated line.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Sequence

from ...ids import blake3_file
from ...manifest import FileEntry, Timing
from ...spec import StreamSpec
from .base import StreamWriter, fsync_path, register_writer


def _as_records(payload) -> list[dict]:
    if isinstance(payload, dict):
        return [payload]
    if isinstance(payload, (list, tuple)):
        return [p if isinstance(p, dict) else {"value": p} for p in payload]
    return [{"value": payload}]


@register_writer("jsonl")
class JsonlWriter(StreamWriter):
    def __init__(self, path, spec, **kw):
        super().__init__(path, spec, **kw)
        self._fh = None
        self._first_t: Optional[float] = None
        self._role = "data"

    def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "ab", buffering=0)

    def write(self, payload, ts_s: Optional[Sequence[float]], seq: int) -> int:
        records = _as_records(payload)
        times = list(ts_s) if ts_s is not None else [None] * len(records)
        for rec, t in zip(records, times):
            line = dict(rec)
            if t is not None:
                line = {"t": t, **rec}
                if self._first_t is None:
                    self._first_t = t
            self._fh.write(json.dumps(line, separators=(",", ":")).encode("utf-8"))
            self._fh.write(b"\n")
            self.n_samples += 1
        self.seq_last = seq
        return len(records)

    def flush(self) -> None:
        if self._fh:
            self._fh.flush()
            fsync_path(self.path)

    def close(self) -> list[FileEntry]:
        if self._fh:
            self._fh.flush()
            fsync_path(self.path)
            self._fh.close()
        return [self._entry(self.n_samples, self._first_t)]

    def _entry(self, n: int, first_t: Optional[float]) -> FileEntry:
        timing = Timing(mode=self.spec.timing_mode, n_samples=n, t_start=first_t,
                        clock_provenance=self.provenance, confidence=self._confidence(),
                        wall_uncertainty_s=self.wall_uncertainty_s)
        return FileEntry(role=self._role, path=f"streams/{self.spec.id}/{self.path.name}",
                         encoding="jsonl", blake3=blake3_file(self.path),
                         bytes=self.path.stat().st_size, timing=timing)

    @classmethod
    def recover(cls, path, spec, *, provenance="host_arrival", wall_uncertainty_s=0.05) -> list[FileEntry]:
        path = Path(path)
        raw = path.read_bytes()
        nl = raw.rfind(b"\n")
        keep = raw[: nl + 1] if nl >= 0 else b""
        if keep != raw:
            path.write_bytes(keep)
            fsync_path(path)
        lines = keep.decode("utf-8").splitlines()
        first_t = None
        if lines:
            try:
                first_t = json.loads(lines[0]).get("t")
            except Exception:
                first_t = None
        self = cls(path, spec, provenance=provenance, wall_uncertainty_s=wall_uncertainty_s)
        return [self._entry(len(lines), first_t)]
