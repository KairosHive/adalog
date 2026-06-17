"""Session reader — the inverse of the writers.

``read_session(manifest_path)`` returns aligned ``ReadStream`` objects built strictly from
the manifest contract (never by guessing filenames/columns). Arrays carry an exact
``index_to_t`` map (from the timing sidecar for anchored_irregular, or uniform for anchored).
This is the single API that adalog-engine and the converter regression tests consume.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pyarrow as pa

from .manifest import Manifest, Timing


@dataclass
class ReadStream:
    id: str
    modality: str
    timing: Optional[Timing]
    channels: list[str] = field(default_factory=list)
    array: Optional[np.ndarray] = None       # (n_samples, n_channels) for array streams
    t: Optional[np.ndarray] = None           # (n_samples,) session seconds
    records: Optional[list[dict]] = None      # for per_sample/event non-array streams
    path: Optional[Path] = None              # for blob/event streams (png)


@dataclass
class ReadSession:
    manifest: Manifest
    root: Path
    streams: dict[str, ReadStream]

    def stream(self, sid: str) -> ReadStream:
        return self.streams[sid]


def _index_to_t(session_root: Path, data_file, timing: Timing) -> Optional[np.ndarray]:
    if timing is None or timing.n_samples is None:
        return None
    if timing.index_to_t == "sidecar":
        # find the sibling timing file
        sidecar = Path(session_root, str(data_file.path)).with_suffix(".timing.ndjson")
        ts: list[float] = []
        if sidecar.exists():
            for line in sidecar.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    ts.extend(json.loads(line)["t"])
        return np.asarray(ts, dtype=np.float64) if ts else None
    # uniform / anchored
    n = timing.n_samples
    t0 = timing.t_start or 0.0
    sf = timing.sfreq_effective or timing.sfreq_nominal or 0.0
    if sf <= 0:
        return None
    return t0 + np.arange(n, dtype=np.float64) / sf


def _read_arrow(path: Path) -> tuple[np.ndarray, list[str]]:
    reader = pa.ipc.open_stream(str(path))
    tbl = reader.read_all()
    cols = tbl.column_names
    arr = np.column_stack([tbl.column(c).to_numpy(zero_copy_only=False) for c in cols]) if cols else np.empty((0, 0))
    return arr, cols


def _read_wav(path: Path, channels: int) -> np.ndarray:
    raw = path.read_bytes()[44:]
    flat = np.frombuffer(raw, dtype="<f4")
    if channels > 1:
        return flat.reshape(-1, channels)
    return flat.reshape(-1, 1)


def _read_jsonl(path: Path) -> list[dict]:
    out = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
    return out


def _read_csv(path: Path) -> list[dict]:
    out = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
        if lines:
            header = lines[0].split(",")
            for ln in lines[1:]:
                vals = ln.split(",")
                out.append(dict(zip(header, vals)))
    return out


def read_session(manifest_path) -> ReadSession:
    manifest_path = Path(manifest_path)
    manifest = Manifest.from_json(manifest_path.read_text(encoding="utf-8"))
    root = manifest_path.parent
    streams: dict[str, ReadStream] = {}
    for s in manifest.streams:
        data_file = s.data_file()
        rs = ReadStream(id=s.id, modality=s.modality,
                        timing=(data_file.timing if data_file else None),
                        channels=list(s.schema_.channels))
        if data_file is None:
            streams[s.id] = rs
            continue
        full = root / data_file.path
        enc = data_file.encoding
        if enc == "arrow_ipc_stream":
            rs.array, rs.channels = _read_arrow(full)
            rs.t = _index_to_t(root, data_file, data_file.timing)
        elif enc == "wav":
            rs.array = _read_wav(full, max(1, len(s.schema_.channels)))
            rs.t = _index_to_t(root, data_file, data_file.timing)
        elif enc in ("jsonl", "pentrace"):
            rs.records = _read_jsonl(full)
            rs.t = np.asarray([r["t"] for r in rs.records if "t" in r], dtype=np.float64) if rs.records else None
        elif enc == "csv_ts":
            rs.records = _read_csv(full)
        elif enc == "png":
            rs.path = full
        streams[s.id] = rs
    return ReadSession(manifest=manifest, root=root, streams=streams)
