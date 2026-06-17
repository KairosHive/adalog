"""Legacy v0 -> v1 session converter (spec §13).

The old "adalog" recorder wrote a per-modality directory tree with naive CSV files and
UTC ISO timestamps (no timezone). This converts one such session into a v1 manifest +
natural-format stream files, going through the real :mod:`adalog.core.recorder.writers`
so that timing (``sfreq_effective`` / gaps / ``index_to_t``) is reconstructed honestly —
never assumed. Timestamps are kept as-is (backwards stamps and gaps are preserved); the
resulting EEG stream is therefore ``anchored_irregular`` with ``approximate`` confidence.
"""
from __future__ import annotations

import csv
import shutil
import warnings
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np

from ..core.ids import new_session_id
from ..core.manifest import (
    AdapterRef,
    ClockAnchorModel,
    ClockBlock,
    FileEntry,
    Manifest,
    Provenance,
    StreamEntry,
    StreamSchema,
    Timing,
)
from ..core.recorder.writers import get_writer
from ..core.spec import (
    ENC_ARROW,
    ENC_JSONL,
    ENC_WAV,
    TIMING_ANCHORED,
    TIMING_ANCHORED_IRREGULAR,
    TIMING_PER_SAMPLE,
    Channel,
    StreamSpec,
)

_EEG_CHANNELS = ["TP9", "AF7", "AF8", "TP10"]
_EEG_COLS = ["eeg-TP9", "eeg-AF7", "eeg-AF8", "eeg-TP10"]
_EEG_CHUNK = 256
_LFS_STUB_MAX_BYTES = 1024


def _parse_utc_ns(stamp: str) -> int:
    """Parse a naive UTC ISO timestamp (e.g. '2025-05-31T23:09:11.593413') to UTC ns."""
    dt = datetime.fromisoformat(stamp.strip())
    # assume UTC; timestamp() would apply local tz for naive datetimes, so do it by hand.
    epoch = datetime(1970, 1, 1)
    return int((dt - epoch).total_seconds() * 1e9)


def _read_csv_rows(path: Path) -> tuple[list[str], list[list[str]]]:
    with open(path, "r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        rows = list(reader)
    if not rows:
        return [], []
    return rows[0], rows[1:]


def _find_first(directory: Path, *patterns: str) -> Optional[Path]:
    for pat in patterns:
        matches = sorted(directory.glob(pat))
        if matches:
            return matches[0]
    return None


def _min_utc_ns(*candidates: Optional[int]) -> Optional[int]:
    vals = [c for c in candidates if c is not None]
    return min(vals) if vals else None


def convert_session(
    old_session_dir: Path,
    out_root: Path,
    *,
    user: str = "phil",
    session_id: Optional[str] = None,
) -> Manifest:
    """Convert one legacy v0 session directory into a v1 session under ``out_root``.

    Returns the written :class:`Manifest`. The manifest + stream files are written to
    ``out_root/<user>/<session_id>/``.
    """
    old_session_dir = Path(old_session_dir)
    out_root = Path(out_root)

    # ---- 1) gather raw timestamps to find t0 ----
    eeg_path = _find_first(old_session_dir / "Eeg", "*.csv")
    text_path = old_session_dir / "Text" / "text.csv"
    tags_path = old_session_dir / "tags.csv"
    audio_path = _find_first(old_session_dir / "Audio", "*.wav")

    eeg_header: list[str] = []
    eeg_rows: list[list[str]] = []
    eeg_ts_ns: list[int] = []
    if eeg_path and eeg_path.exists():
        eeg_header, eeg_rows = _read_csv_rows(eeg_path)
        ts_idx = eeg_header.index("timestamp")
        eeg_ts_ns = [_parse_utc_ns(r[ts_idx]) for r in eeg_rows]

    text_rows: list[tuple[int, str]] = []  # (utc_ns, content)
    if text_path.exists():
        header, rows = _read_csv_rows(text_path)
        ts_idx = header.index("timestamp")
        c_idx = header.index("content")
        prev: Optional[tuple[str, str]] = None
        for r in rows:
            if len(r) <= max(ts_idx, c_idx):
                continue
            key = (r[ts_idx], r[c_idx])
            if key == prev:  # dedupe consecutive identical (timestamp, content)
                continue
            prev = key
            text_rows.append((_parse_utc_ns(r[ts_idx]), r[c_idx]))

    tags: list[str] = []
    if tags_path.exists():
        header, rows = _read_csv_rows(tags_path)
        if rows:
            t_idx = header.index("tags")
            seen: set[str] = set()
            # take the LAST row primarily; union across rows for append-on-edit history.
            for r in reversed(rows):
                if len(r) <= t_idx:
                    continue
                for tag in (t.strip() for t in r[t_idx].split(",")):
                    if tag and tag not in seen:
                        seen.add(tag)
                        tags.append(tag)

    audio_start_ns: Optional[int] = None
    audio_usable = False
    if audio_path and audio_path.exists():
        size = audio_path.stat().st_size
        head = audio_path.read_bytes()[:64]
        if size <= _LFS_STUB_MAX_BYTES or head.startswith(b"version https://git-lfs"):
            warnings.warn(
                f"audio file {audio_path.name} looks like a git-LFS pointer stub "
                f"({size} bytes); skipping audio.",
                stacklevel=2,
            )
        else:
            audio_usable = True
            audio_start_ns = _audio_start_ns(audio_path)

    t0_utc_ns = _min_utc_ns(
        min(eeg_ts_ns) if eeg_ts_ns else None,
        min(t[0] for t in text_rows) if text_rows else None,
        audio_start_ns,
    )
    if t0_utc_ns is None:
        raise ValueError(f"no timestamped data found in {old_session_dir}")

    def session_seconds(utc_ns: int) -> float:
        return (utc_ns - t0_utc_ns) / 1e9

    sid = session_id or new_session_id(salt=user)
    out_dir = out_root / user / sid
    out_dir.mkdir(parents=True, exist_ok=True)

    streams: list[StreamEntry] = []
    duration_s = 0.0

    # ---- 2) EEG -> arrow_ipc_stream ----
    if eeg_rows:
        col_idx = [eeg_header.index(c) for c in _EEG_COLS]
        eeg_spec = StreamSpec(
            id="eeg",
            modality="eeg",
            channels=[Channel(name=ch, units="uV", dtype="float32") for ch in _EEG_CHANNELS],
            units="uV",
            dtype="float32",
            encoding=ENC_ARROW,
            timing_mode=TIMING_ANCHORED_IRREGULAR,
            sfreq_nominal=256.0,
        )
        writer = get_writer(ENC_ARROW)(
            out_dir / "streams" / "eeg" / "eeg.arrow", eeg_spec, provenance="reconstructed"
        )
        writer.open()
        n = len(eeg_rows)
        for start in range(0, n, _EEG_CHUNK):
            end = min(start + _EEG_CHUNK, n)
            chunk = eeg_rows[start:end]
            arr = np.array(
                [[float(r[i]) for i in col_idx] for r in chunk], dtype=np.float32
            )
            ts_s = [session_seconds(eeg_ts_ns[k]) for k in range(start, end)]
            writer.write(arr, ts_s, seq=start)
        files = writer.close()
        streams.append(
            StreamEntry(
                id="eeg",
                modality="eeg",
                adapter=AdapterRef(id="converter"),
                schema=StreamSchema(channels=list(_EEG_CHANNELS), units="uV", dtype="float32"),
                files=files,
                status="complete",
            )
        )
        for f in files:
            if f.role == "data" and f.timing is not None:
                f.timing.confidence = "approximate"
                f.timing.clock_provenance = "reconstructed"
        duration_s = max(duration_s, max(session_seconds(t) for t in eeg_ts_ns))

    # ---- 3) Text -> jsonl ----
    if text_rows:
        text_spec = StreamSpec(
            id="text",
            modality="text",
            encoding=ENC_JSONL,
            timing_mode=TIMING_PER_SAMPLE,
        )
        twriter = get_writer(ENC_JSONL)(
            out_dir / "streams" / "text" / "text.ndjson", text_spec, provenance="reconstructed"
        )
        twriter.open()
        for i, (utc_ns, content) in enumerate(text_rows):
            twriter.write({"word": content}, [session_seconds(utc_ns)], seq=i)
        tfiles = twriter.close()
        streams.append(
            StreamEntry(
                id="text",
                modality="text",
                adapter=AdapterRef(id="converter"),
                schema=StreamSchema(channels=["word"]),
                files=tfiles,
                status="complete",
            )
        )
        duration_s = max(duration_s, max(session_seconds(t[0]) for t in text_rows))

    # ---- 5) Audio -> wav (copied), only if a real (non-stub) file exists ----
    if audio_usable and audio_path is not None:
        dest = out_dir / "streams" / "audio" / "audio.wav"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(audio_path, dest)
        from ..core.ids import blake3_file

        t_start = session_seconds(audio_start_ns) if audio_start_ns is not None else 0.0
        timing = Timing(
            mode=TIMING_ANCHORED,
            sfreq_nominal=48000.0,
            t_start=t_start,
            clock_provenance="reconstructed",
            confidence="approximate",
        )
        files = [
            FileEntry(
                role="data",
                path="streams/audio/audio.wav",
                encoding=ENC_WAV,
                blake3=blake3_file(dest),
                bytes=dest.stat().st_size,
                timing=timing,
            )
        ]
        streams.append(
            StreamEntry(
                id="audio",
                modality="audio",
                adapter=AdapterRef(id="converter"),
                schema=StreamSchema(channels=["mic"], dtype="float32"),
                files=files,
                status="complete",
            )
        )

    # ---- 6) build + write manifest ----
    manifest = Manifest(
        session_id=sid,
        status="complete",
        provenance=Provenance(user_id=user, app="adalog-convert", created_with="standalone"),
        clock=ClockBlock(t0_anchor=ClockAnchorModel(t=0.0, mono_ns=0, utc_ns=t0_utc_ns)),
        duration_s=duration_s,
        tags=tags,
        streams=streams,
    )
    (out_dir / "manifest.json").write_text(manifest.to_json(), encoding="utf-8")
    return manifest


def _audio_start_ns(audio_path: Path) -> Optional[int]:
    """Derive the audio start time from the legacy filename, e.g.
    ``audio_2025-05-25T00-06-33-938909Z.wav`` -> UTC ns. Returns None if unparseable."""
    name = audio_path.stem
    if "_" not in name:
        return None
    stamp = name.split("_", 1)[1].rstrip("Z")
    # legacy form: YYYY-MM-DDTHH-MM-SS-ffffff  (dashes in the time + micros)
    try:
        date_part, time_part = stamp.split("T", 1)
        bits = time_part.split("-")
        if len(bits) >= 3:
            hh, mm, ss = bits[0], bits[1], bits[2]
            micros = bits[3] if len(bits) > 3 else "0"
            iso = f"{date_part}T{hh}:{mm}:{ss}.{micros}"
            return _parse_utc_ns(iso)
    except (ValueError, IndexError):
        return None
    return None
