"""Float32 IEEE WAV writer for audio (anchored mode), pure-stdlib (no soundfile in core).

Audio is uniform-rate, so the data file is a plain WAV; a tiny block-start sidecar records
``(frame_index, t)`` per written block so ``t_start`` and a *measured* ``sfreq_effective``
survive a crash. ``recover()`` truncates the data to whole frames and rewrites the RIFF
header from the frame count; the sidecar is truncated to its last complete line.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

from ...ids import blake3_file
from ...manifest import FileEntry, Timing
from ...spec import StreamSpec
from .base import StreamWriter, append_ndjson, fsync_path, register_writer

_HEADER_SIZE = 44


def _wav_header(n_frames: int, channels: int, sample_rate: int) -> bytes:
    bits = 32
    byte_rate = sample_rate * channels * (bits // 8)
    block_align = channels * (bits // 8)
    data_size = n_frames * block_align
    return b"".join([
        b"RIFF", struct.pack("<I", 36 + data_size), b"WAVE",
        b"fmt ", struct.pack("<I", 16), struct.pack("<H", 3),  # 3 = IEEE float
        struct.pack("<H", channels), struct.pack("<I", sample_rate),
        struct.pack("<I", byte_rate), struct.pack("<H", block_align), struct.pack("<H", bits),
        b"data", struct.pack("<I", data_size),
    ])


def _sidecar_path(path: Path) -> Path:
    return path.with_suffix(".blocks.ndjson")


@register_writer("wav")
class WavWriter(StreamWriter):
    def __init__(self, path, spec, **kw):
        super().__init__(path, spec, **kw)
        self._channels = max(1, len(spec.channels))
        self._rate = int(spec.sfreq_nominal or 48000)
        self._fh = None
        self._sidecar = None

    def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "wb")
        self._fh.write(_wav_header(0, self._channels, self._rate))  # placeholder
        self._fh.flush()
        fsync_path(self.path)
        self._sidecar = open(_sidecar_path(self.path), "ab", buffering=0)

    def write(self, payload, ts_s: Optional[Sequence[float]], seq: int) -> int:
        arr = np.asarray(payload, dtype=np.float32)
        if arr.ndim == 1:
            arr = arr.reshape(-1, self._channels)
        count = arr.shape[0]
        block_start_t = (ts_s[0] if ts_s is not None and len(ts_s) else None)
        append_ndjson(self._sidecar, {"frame_index": self.n_samples, "t": block_start_t, "seq": seq})
        self._fh.write(arr.tobytes(order="C"))
        self._fh.flush()
        self.n_samples += count
        self.seq_last = seq
        return count

    def flush(self) -> None:
        if self._fh:
            self._fh.flush()
            fsync_path(self.path)
        if self._sidecar:
            self._sidecar.flush()

    def _patch_header(self) -> None:
        with open(self.path, "r+b") as fh:
            fh.seek(0)
            fh.write(_wav_header(self.n_samples, self._channels, self._rate))

    def close(self) -> list[FileEntry]:
        if self._fh:
            self._fh.flush()
            self._fh.close()
        self._patch_header()
        fsync_path(self.path)
        if self._sidecar:
            self._sidecar.close()
        return self._finalize_entries()

    def _finalize_entries(self) -> list[FileEntry]:
        sidecar = _sidecar_path(self.path)
        t_start, sfreq_eff = self._measure(sidecar)
        timing = Timing(mode=self.spec.timing_mode, sfreq_nominal=float(self._rate),
                        sfreq_effective=sfreq_eff, t_start=t_start, n_samples=self.n_samples,
                        index_to_t="uniform", clock_provenance=self.provenance,
                        confidence=self._confidence(), wall_uncertainty_s=self.wall_uncertainty_s)
        files = [FileEntry(role="data", path=f"streams/{self.spec.id}/{self.path.name}", encoding="wav",
                           blake3=blake3_file(self.path), bytes=self.path.stat().st_size, timing=timing)]
        if sidecar.exists():
            files.append(FileEntry(role="timing", path=f"streams/{self.spec.id}/{sidecar.name}",
                                   encoding="jsonl", blake3=blake3_file(sidecar), bytes=sidecar.stat().st_size))
        return files

    def _measure(self, sidecar: Path):
        if not sidecar.exists():
            return None, float(self._rate)
        idx, ts = [], []
        for line in sidecar.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("t") is not None:
                idx.append(rec["frame_index"])
                ts.append(rec["t"])
        if len(ts) >= 2:
            slope = np.polyfit(np.asarray(idx, float), np.asarray(ts, float), 1)[0]
            return float(ts[0]), (1.0 / slope if slope > 0 else float(self._rate))
        if ts:
            return float(ts[0]), float(self._rate)
        return None, float(self._rate)

    @classmethod
    def recover(cls, path, spec, *, provenance="host_arrival", wall_uncertainty_s=0.05) -> list[FileEntry]:
        path = Path(path)
        self = cls(path, spec, provenance=provenance, wall_uncertainty_s=wall_uncertainty_s)
        size = path.stat().st_size
        data_bytes = max(0, size - _HEADER_SIZE)
        frame_bytes = self._channels * 4
        n_frames = data_bytes // frame_bytes
        good = _HEADER_SIZE + n_frames * frame_bytes
        if good != size:
            with open(path, "r+b") as fh:
                fh.truncate(good)
        self.n_samples = n_frames
        self._patch_header()
        fsync_path(path)
        sidecar = _sidecar_path(path)
        if sidecar.exists():  # truncate sidecar to last complete line
            raw = sidecar.read_bytes()
            nl = raw.rfind(b"\n")
            if nl + 1 != len(raw):
                sidecar.write_bytes(raw[: nl + 1] if nl >= 0 else b"")
        return self._finalize_entries()
