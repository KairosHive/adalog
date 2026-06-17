"""PNG snapshot writer (event mode). Atomic write (temp+rename) => never torn."""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

from ...ids import blake3_file
from ...manifest import FileEntry, Timing
from ...spec import StreamSpec
from .base import StreamWriter, fsync_path, register_writer


@register_writer("png")
class PngWriter(StreamWriter):
    """Writes the latest PNG bytes atomically; records one event per write."""

    def __init__(self, path, spec, **kw):
        super().__init__(path, spec, **kw)
        self._events: list[float] = []
        self._role = "snapshot"

    def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, payload, ts_s: Optional[Sequence[float]], seq: int) -> int:
        data = payload if isinstance(payload, (bytes, bytearray)) else bytes(payload)
        tmp = self.path.with_suffix(".png.tmp")
        tmp.write_bytes(data)
        fsync_path(tmp)
        tmp.replace(self.path)  # atomic
        fsync_path(self.path)
        if ts_s is not None and len(ts_s):
            self._events.append(float(ts_s[0]))
        self.n_samples += 1
        self.seq_last = seq
        return 1

    def flush(self) -> None:
        pass

    def close(self) -> list[FileEntry]:
        return [self._entry()]

    def _entry(self) -> FileEntry:
        timing = Timing(mode="event", n_samples=len(self._events),
                        clock_provenance=self.provenance, confidence=self._confidence(),
                        wall_uncertainty_s=self.wall_uncertainty_s)
        b3 = blake3_file(self.path) if self.path.exists() else None
        size = self.path.stat().st_size if self.path.exists() else None
        return FileEntry(role=self._role, path=f"streams/{self.spec.id}/{self.path.name}",
                         encoding="png", blake3=b3, bytes=size, timing=timing)

    @classmethod
    def recover(cls, path, spec, *, provenance="host_arrival", wall_uncertainty_s=0.05) -> list[FileEntry]:
        # Atomic write => the file is either a complete prior snapshot or absent.
        self = cls(path, spec, provenance=provenance, wall_uncertainty_s=wall_uncertainty_s)
        if Path(path).exists():
            self.n_samples = 1
            self._events = [0.0]
        return [self._entry()]
