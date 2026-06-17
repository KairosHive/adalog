"""Session lifecycle (spec §7): the FSM that wraps RecordingCore + clock + manifest + events.

States: created -> armed -> recording <-> paused -> stopped; plus recovering -> recovered
(entered automatically when a manifest.lock is found at launch). A valid, complete session
directory is produced with zero network and zero auth (invariant #8).
"""
from __future__ import annotations

import json
import platform
import socket
from pathlib import Path
from typing import Optional

from .. import __version__
from .clock import SessionClock
from .envelope import StreamPacket
from .ids import new_session_id
from .manifest import (
    AdapterRef,
    ClockAnchorModel,
    ClockBlock,
    DeviceRef,
    FileEntry,
    Manifest,
    Pause,
    Provenance,
    StreamEntry,
    StreamSchema,
    Subject,
    Timing,
    reconcile,
)
from .recorder.core import RecordingCore, _data_filename
from .recorder.writers import get_writer
from .spec import Channel, StreamSpec

CREATED, ARMED, RECORDING, PAUSED, STOPPED, RECOVERED = (
    "created", "armed", "recording", "paused", "stopped", "recovered"
)
LOCK_NAME = "manifest.lock"
MANIFEST_NAME = "manifest.json"
EVENTS_NAME = "events.ndjson"


def _draft_stream_entry(spec: StreamSpec) -> StreamEntry:
    """A draft StreamEntry written at arm so recovery can reconstruct the spec."""
    data = FileEntry(role="data", path=f"streams/{spec.id}/{_data_filename(spec)}", encoding=spec.encoding,
                     timing=Timing(mode=spec.timing_mode, sfreq_nominal=spec.sfreq_nominal))
    return StreamEntry(id=spec.id, modality=spec.modality, adapter=AdapterRef(id=spec.id),
                       schema=StreamSchema(channels=spec.channel_names, units=spec.units, dtype=spec.dtype),
                       files=[data], status="complete")


def _provenance() -> Provenance:
    return Provenance(app="adalog-sense", app_version=__version__,
                      host=socket.gethostname(), os=f"{platform.system()}-{platform.release()}",
                      created_with="standalone")


class Session:
    def __init__(self, session_dir: Path, clock: SessionClock, *, session_id: str,
                 subject: Subject, provenance: Provenance, label: str = "", tags: Optional[list[str]] = None):
        self.dir = Path(session_dir)
        self.clock = clock
        self.session_id = session_id
        self.subject = subject
        self.provenance = provenance
        self.label = label
        self.tags = list(tags or [])
        self.state = CREATED
        self.core: Optional[RecordingCore] = None
        self.specs: dict[str, StreamSpec] = {}
        self.pauses: list[Pause] = []
        self._pause_from: Optional[float] = None
        self._events_fh = None

    # ---- construction ----
    @classmethod
    def create(cls, sessions_root, *, user: str = "u_local", subject: Optional[Subject] = None,
               label: str = "", tags: Optional[list[str]] = None, session_id: Optional[str] = None,
               clock: Optional[SessionClock] = None) -> "Session":
        clock = clock or SessionClock()
        sid = session_id or new_session_id(salt=f"{user}@{socket.gethostname()}")
        sdir = Path(sessions_root) / user / sid
        sdir.mkdir(parents=True, exist_ok=True)
        prov = _provenance()
        prov.user_id = user
        s = cls(sdir, clock, session_id=sid, subject=subject or Subject(id=user), provenance=prov,
                label=label, tags=tags)
        s.core = RecordingCore(sdir, clock)  # created up front so a supervisor can add streams
        (sdir / LOCK_NAME).write_text("recording", encoding="utf-8")
        s._events_fh = open(sdir / EVENTS_NAME, "ab", buffering=0)
        return s

    # ---- events ----
    def _event(self, kind: str, **fields) -> None:
        if self._events_fh is None:
            self._events_fh = open(self.dir / EVENTS_NAME, "ab", buffering=0)
        rec = {"t": self.clock.now_s(), "kind": kind, **fields}
        self._events_fh.write(json.dumps(rec, separators=(",", ":")).encode("utf-8"))
        self._events_fh.write(b"\n")
        self._events_fh.flush()

    def add_tag(self, tag: str) -> None:
        if tag not in self.tags:
            self.tags.append(tag)
        self._event("tag", tag=tag)

    # ---- FSM ----
    def arm(self, specs: list[StreamSpec]) -> None:
        """Direct path: add the given streams to the core, then commit the draft manifest."""
        if self.state != CREATED:
            raise RuntimeError(f"arm requires state {CREATED}, in {self.state}")
        if not specs:
            raise RuntimeError("arm requires >= 1 stream")
        for spec in specs:
            self.specs[spec.id] = spec
            self.core.add_stream(spec, provenance=getattr(spec, "_provenance", "host_arrival"),
                                 adapter=getattr(spec, "_adapter", None), device=getattr(spec, "_device", None))
        self.commit_draft()

    def commit_draft(self) -> None:
        """Service path: streams already added to the core (e.g. by a supervisor). Write the
        draft manifest from the core's current streams and move to armed."""
        if self.state != CREATED:
            raise RuntimeError(f"commit_draft requires state {CREATED}, in {self.state}")
        specs = self.core.specs()
        if not specs:
            raise RuntimeError("commit_draft requires >= 1 stream")
        for spec in specs:
            self.specs.setdefault(spec.id, spec)
        self._write_manifest(status="recording", streams=[_draft_stream_entry(s) for s in specs])
        self.state = ARMED

    def add_stream(self, spec: StreamSpec, *, provenance: str = "host_arrival",
                   adapter: Optional[AdapterRef] = None, device: Optional[DeviceRef] = None) -> None:
        """Late-join an already-armed instance after start (spec §6.5)."""
        if self.state not in (ARMED, RECORDING):
            raise RuntimeError(f"add_stream requires armed/recording, in {self.state}")
        self.specs[spec.id] = spec
        self.core.add_stream(spec, provenance=provenance, adapter=adapter, device=device)

    def start(self) -> None:
        if self.state != ARMED:
            raise RuntimeError(f"start requires state {ARMED}, in {self.state}")
        self.state = RECORDING
        self._event("start")

    def ingest(self, packet: StreamPacket) -> bool:
        """Returns True if written, False if dropped (paused / not recording)."""
        if self.state != RECORDING:
            return False
        self.core.ingest(packet)
        return True

    def pause(self) -> None:
        if self.state != RECORDING:
            raise RuntimeError("pause requires recording")
        self._pause_from = self.clock.now_s()
        self.state = PAUSED
        self._event("pause")

    def resume(self) -> None:
        if self.state != PAUSED:
            raise RuntimeError("resume requires paused")
        if self._pause_from is not None:
            self.pauses.append(Pause(from_t=self._pause_from, to_t=self.clock.now_s()))
            self._pause_from = None
        self.state = RECORDING
        self._event("resume")

    def stop(self) -> Manifest:
        if self.state not in (RECORDING, PAUSED):
            raise RuntimeError(f"stop requires recording/paused, in {self.state}")
        if self.state == PAUSED and self._pause_from is not None:
            self.pauses.append(Pause(from_t=self._pause_from, to_t=self.clock.now_s()))
            self._pause_from = None
        self.clock.reanchor()
        entries = self.core.finalize()
        manifest = self._build_manifest("complete", entries)
        reconcile(manifest, self.core.counts())
        self._event("stop")
        self._write_manifest_obj(manifest)
        self._cleanup_lock()
        self.state = STOPPED
        if self._events_fh:
            self._events_fh.close()
            self._events_fh = None
        return manifest

    # ---- manifest io ----
    def _clock_block(self) -> ClockBlock:
        anchors = [ClockAnchorModel(t=a.t, mono_ns=a.mono_ns, utc_ns=a.utc_ns) for a in self.clock.anchors]
        return ClockBlock(t0_anchor=anchors[0], reanchors=anchors[1:], host_drift_ppm=self.clock.host_drift_ppm,
                          boottime_used=self.clock.boottime_used, wall_uncertainty_s=self.clock.wall_uncertainty_s)

    def _build_manifest(self, status: str, streams: list[StreamEntry]) -> Manifest:
        return Manifest(session_id=self.session_id, status=status, label=self.label, subject=self.subject,
                        provenance=self.provenance, clock=self._clock_block(), duration_s=self.clock.now_s(),
                        pauses=self.pauses, tags=self.tags, streams=streams)

    def _write_manifest(self, status: str, streams: list[StreamEntry]) -> None:
        self._write_manifest_obj(self._build_manifest(status, streams))

    def _write_manifest_obj(self, manifest: Manifest) -> None:
        tmp = self.dir / (MANIFEST_NAME + ".tmp")
        tmp.write_text(manifest.to_json(), encoding="utf-8")
        tmp.replace(self.dir / MANIFEST_NAME)

    def _cleanup_lock(self) -> None:
        lock = self.dir / LOCK_NAME
        if lock.exists():
            lock.unlink()


# ---- crash recovery ----
def needs_recovery(session_dir) -> bool:
    return (Path(session_dir) / LOCK_NAME).exists()


def recover_session(session_dir) -> Manifest:
    """Recover a session left in 'recording' state by a crash (spec §5.5).

    Replays each stream's format-aware writer.recover(), rebuilds the manifest with honest
    salvaged counts/hashes, sets status 'recovered', and removes the lock.
    """
    sdir = Path(session_dir)
    draft = Manifest.from_json((sdir / MANIFEST_NAME).read_text(encoding="utf-8"))
    new_streams: list[StreamEntry] = []
    counts: dict[str, dict] = {}
    for s in draft.streams:
        data = s.data_file()
        if data is None:
            new_streams.append(s)
            continue
        timing = data.timing
        spec = StreamSpec(
            id=s.id, modality=s.modality,
            channels=[Channel(name) for name in s.schema_.channels],
            encoding=data.encoding,
            timing_mode=(timing.mode if timing else "per_sample"),
            sfreq_nominal=(timing.sfreq_nominal if timing else None),
        )
        path = sdir / data.path
        if path.exists():
            files = get_writer(data.encoding).recover(path, spec)
        else:
            files = []
        df = next((f for f in files if f.role == "data"), files[0] if files else None)
        persisted = (df.timing.n_samples if df and df.timing and df.timing.n_samples is not None else 0)
        counts[s.id] = {"produced": persisted, "persisted": persisted}  # produced unknown post-crash
        new_streams.append(StreamEntry(id=s.id, modality=s.modality, adapter=s.adapter, device=s.device,
                                       schema=s.schema_, files=files, status="complete"))
    recovered = Manifest(session_id=draft.session_id, status="recovered", label=draft.label,
                         subject=draft.subject, provenance=draft.provenance, clock=draft.clock,
                         duration_s=draft.duration_s, pauses=draft.pauses, tags=draft.tags, streams=new_streams)
    reconcile(recovered, counts)
    tmp = sdir / (MANIFEST_NAME + ".tmp")
    tmp.write_text(recovered.to_json(), encoding="utf-8")
    tmp.replace(sdir / MANIFEST_NAME)
    lock = sdir / LOCK_NAME
    if lock.exists():
        lock.unlink()
    return recovered
