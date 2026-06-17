"""CSV writer for generic multivariate time series (per_sample). Columns: t + channels."""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

from ...ids import blake3_file
from ...manifest import FileEntry, Timing
from ...spec import StreamSpec
from .base import StreamWriter, fsync_path, register_writer


@register_writer("csv_ts")
class CsvTsWriter(StreamWriter):
    def __init__(self, path, spec, **kw):
        super().__init__(path, spec, **kw)
        self._cols = [c.name for c in spec.channels]
        self._fh = None
        self._first_t: Optional[float] = None

    def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "ab", buffering=0)
        if self.path.stat().st_size == 0:
            self._fh.write(("t," + ",".join(self._cols) + "\n").encode("utf-8"))

    def write(self, payload, ts_s: Optional[Sequence[float]], seq: int) -> int:
        # payload: dict (single row) or list of dicts; ts_s aligned
        rows = [payload] if isinstance(payload, dict) else list(payload)
        times = list(ts_s) if ts_s is not None else [None] * len(rows)
        for row, t in zip(rows, times):
            vals = [("" if t is None else repr(t))] + [str(row.get(c, "")) for c in self._cols]
            self._fh.write((",".join(vals) + "\n").encode("utf-8"))
            if t is not None and self._first_t is None:
                self._first_t = t
            self.n_samples += 1
        self.seq_last = seq
        return len(rows)

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

    def _entry(self, n, first_t) -> FileEntry:
        timing = Timing(mode=self.spec.timing_mode, n_samples=n, t_start=first_t,
                        clock_provenance=self.provenance, confidence=self._confidence(),
                        wall_uncertainty_s=self.wall_uncertainty_s)
        return FileEntry(role="data", path=f"streams/{self.spec.id}/{self.path.name}",
                         encoding="csv_ts", blake3=blake3_file(self.path),
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
        n = max(0, len(lines) - 1)  # minus header
        first_t = None
        if n >= 1 and len(lines) > 1:
            try:
                first_t = float(lines[1].split(",")[0])
            except Exception:
                first_t = None
        self = cls(path, spec, provenance=provenance, wall_uncertainty_s=wall_uncertainty_s)
        return [self._entry(n, first_t)]
