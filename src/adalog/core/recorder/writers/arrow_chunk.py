"""Arrow IPC *stream* writer for array streams (per_sample / anchored_irregular).

Data is written contiguously (gap-free index space) as a sequence of length-prefixed
encapsulated RecordBatch messages. A per-batch NDJSON *timing sidecar* records the raw
per-sample session times, from which ``sfreq_effective`` / exact ``index_to_t`` / ``gaps``
are reconstructed at finalize — no uniform intra-chunk spacing is ever assumed.

Crash safety: the schema message is fsynced before the first batch. A torn tail loses at
most the last incomplete record batch; ``recover()`` forward-scans the complete batches,
rewrites a clean stream, and truncates the sidecar to match.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Sequence

import numpy as np
import pyarrow as pa

from ...manifest import FileEntry, Gap, Timing
from ...spec import StreamSpec
from ...ids import blake3_file
from .base import StreamWriter, append_ndjson, fsync_path, register_writer

_ARROW_DTYPE = {
    "float32": pa.float32(), "float64": pa.float64(),
    "int16": pa.int16(), "int32": pa.int32(), "int64": pa.int64(),
    "uint8": pa.uint8(), "uint16": pa.uint16(),
}


def _schema(spec: StreamSpec) -> pa.Schema:
    fields = []
    for ch in spec.channels:
        fields.append(pa.field(ch.name, _ARROW_DTYPE.get(ch.dtype, pa.float32())))
    if not fields:  # generic single-column fallback
        fields = [pa.field("v", pa.float32())]
    return pa.schema(fields)


def _sidecar_path(path: Path) -> Path:
    return path.with_suffix(".timing.ndjson")


def _reconstruct_timing(spec: StreamSpec, sidecar: Path, provenance: str, wall_uncertainty_s: float,
                        confidence: str) -> Timing:
    ts: list[float] = []
    if sidecar.exists():
        with open(sidecar, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                ts.extend(rec["t"])
    n = len(ts)
    timing = Timing(
        mode=spec.timing_mode, sfreq_nominal=spec.sfreq_nominal, n_samples=n,
        index_to_t="sidecar", clock_provenance=provenance, confidence=confidence,
        wall_uncertainty_s=wall_uncertainty_s,
    )
    if n >= 2:
        t_arr = np.asarray(ts, dtype=np.float64)
        timing.t_start = float(t_arr[0])
        idx = np.arange(n, dtype=np.float64)
        slope = np.polyfit(idx, t_arr, 1)[0]  # seconds per sample
        sfreq_eff = (1.0 / slope) if slope > 0 else (spec.sfreq_nominal or 0.0)
        timing.sfreq_effective = float(sfreq_eff)
        thresh = 2.0 / sfreq_eff if sfreq_eff > 0 else float("inf")
        dts = np.diff(t_arr)
        for i in np.nonzero(dts > thresh)[0]:
            timing.gaps.append(Gap(index=int(i + 1), t=float(t_arr[i + 1]),
                                   duration_s=float(dts[i]), reason="gap"))
    elif n == 1:
        timing.t_start = float(ts[0])
        timing.sfreq_effective = spec.sfreq_nominal
    return timing


@register_writer("arrow_ipc_stream")
class ArrowChunkWriter(StreamWriter):
    def __init__(self, path, spec, **kw):
        super().__init__(path, spec, **kw)
        self._schema = _schema(spec)
        self._sink = None
        self._writer = None
        self._sidecar = None
        self._batch = 0

    def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._sink = open(self.path, "wb")
        self._writer = pa.ipc.new_stream(self._sink, self._schema)
        self._sink.flush()
        fsync_path(self.path)  # schema message durable before first batch
        self._sidecar = open(_sidecar_path(self.path), "ab", buffering=0)

    def write(self, payload, ts_s: Optional[Sequence[float]], seq: int) -> int:
        arr = np.asarray(payload)
        if arr.ndim == 1:
            arr = arr.reshape(-1, 1)
        count = arr.shape[0]
        cols = [pa.array(arr[:, i], type=self._schema.field(i).type) for i in range(len(self._schema))]
        batch = pa.record_batch(cols, schema=self._schema)
        self._writer.write_batch(batch)
        self._sink.flush()
        if ts_s is None:
            raise ValueError(f"{self.spec.id}: arrow stream requires per-sample ts_s")
        append_ndjson(self._sidecar, {"batch": self._batch, "first_index": self.n_samples,
                                      "count": count, "t": list(ts_s), "seq": seq})
        self.n_samples += count
        self.seq_last = seq
        self._batch += 1
        return count

    def flush(self) -> None:
        if self._sink:
            self._sink.flush()
            fsync_path(self.path)
        if self._sidecar:
            self._sidecar.flush()

    def close(self) -> list[FileEntry]:
        if self._writer:
            self._writer.close()
        if self._sink:
            self._sink.flush()
            fsync_path(self.path)
            self._sink.close()
        if self._sidecar:
            self._sidecar.close()
        return self._finalize_entries()

    def _finalize_entries(self) -> list[FileEntry]:
        sidecar = _sidecar_path(self.path)
        timing = _reconstruct_timing(self.spec, sidecar, self.provenance, self.wall_uncertainty_s, self._confidence())
        rel = self.path.name
        data_entry = FileEntry(
            role="data", path=f"streams/{self.spec.id}/{rel}", encoding=self.encoding,
            blake3=blake3_file(self.path), bytes=self.path.stat().st_size, timing=timing,
        )
        files = [data_entry]
        if sidecar.exists():
            files.append(FileEntry(role="timing", path=f"streams/{self.spec.id}/{sidecar.name}",
                                   encoding="jsonl", blake3=blake3_file(sidecar), bytes=sidecar.stat().st_size))
        return files

    @classmethod
    def recover(cls, path, spec, *, provenance="host_arrival", wall_uncertainty_s=0.05) -> list[FileEntry]:
        path = Path(path)
        # 1) forward-scan complete record batches
        batches = []
        try:
            reader = pa.ipc.open_stream(str(path))
            while True:
                try:
                    batches.append(reader.read_next_batch())
                except StopIteration:
                    break
                except Exception:
                    break  # torn tail
        except Exception:
            # header itself unreadable -> failed stream
            self = cls(path, spec, provenance=provenance, wall_uncertainty_s=wall_uncertainty_s)
            return self._finalize_entries()
        # 2) rewrite a clean stream with only the salvaged batches
        tmp = path.with_suffix(".arrow.recovered")
        with open(tmp, "wb") as sink:
            w = pa.ipc.new_stream(sink, _schema(spec))
            for b in batches:
                w.write_batch(b)
            w.close()
            sink.flush()
        tmp.replace(path)
        fsync_path(path)
        # 3) truncate the sidecar to the salvaged batch count
        sidecar = _sidecar_path(path)
        if sidecar.exists():
            lines = sidecar.read_text(encoding="utf-8").splitlines()
            keep = lines[: len(batches)]
            sidecar.write_text(("\n".join(keep) + ("\n" if keep else "")), encoding="utf-8")
        # 4) rebuild FileEntries
        self = cls(path, spec, provenance=provenance, wall_uncertainty_s=wall_uncertainty_s)
        self.n_samples = sum(b.num_rows for b in batches)
        return self._finalize_entries()
