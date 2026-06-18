"""RecordingCore — the integrator.

Owns the SessionClock, a per-stream DeviceClock, a per-stream lossless StreamPipe+writer,
and the (separate) monitor plane. Adapters call :meth:`ingest`; the Core stamps device
time → session time, writes losslessly, and fans a best-effort copy to monitor taps. At
:meth:`finalize` it composes the per-stream manifest entries (with reconstructed timing,
counted drops, and reconcile counts).
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from ..clock import SessionClock
from ..device_clock import DeviceClock, PROV_HOST_ARRIVAL
from ..envelope import StreamPacket, validate_packet
from ..manifest import AdapterRef, Drop, DeviceRef, DerivationRef, StreamEntry, StreamSchema
from ..spec import BP_SPILL, StreamSpec
from .ringbuffer import StreamPipe, _Item
from .writers import get_writer


@dataclass
class _Stream:
    spec: StreamSpec
    writer: object
    pipe: StreamPipe
    device_clock: DeviceClock
    adapter: AdapterRef
    device: DeviceRef
    taps: list[Callable[[StreamPacket], None]] = field(default_factory=list)
    last_packet: Optional[StreamPacket] = None
    files: list = field(default_factory=list)
    counts: dict = field(default_factory=dict)
    segments: int = 1


def _data_filename(spec: StreamSpec) -> str:
    ext = {"arrow_ipc_stream": "arrow", "wav": "wav", "jsonl": "ndjson", "csv_ts": "csv",
           "pentrace": "ndjson", "png": "png"}.get(spec.encoding, "dat")
    return f"{spec.id}.{ext}"


class RecordingCore:
    def __init__(self, session_dir: Path, clock: SessionClock, *, ring_capacity: int = 512):
        self.session_dir = Path(session_dir)
        self.clock = clock
        self.ring_capacity = ring_capacity
        self._streams: dict[str, _Stream] = {}
        self._finalized = False
        # taps are added/removed from the bridge event-loop thread and iterated from each
        # adapter's ingest thread — guard the lists so iteration sees a stable snapshot.
        self._taps_lock = threading.Lock()

    # ---- stream lifecycle ----
    def add_stream(self, spec: StreamSpec, *, provenance: str = PROV_HOST_ARRIVAL,
                   adapter: Optional[AdapterRef] = None, device: Optional[DeviceRef] = None,
                   filename: Optional[str] = None) -> None:
        if spec.id in self._streams:
            raise ValueError(f"stream {spec.id!r} already added")
        stream_dir = self.session_dir / "streams" / spec.id
        stream_dir.mkdir(parents=True, exist_ok=True)
        path = stream_dir / (filename or _data_filename(spec))
        writer = get_writer(spec.encoding)(path, spec, provenance=provenance,
                                           wall_uncertainty_s=self.clock.wall_uncertainty_s)
        writer.open()
        wal_path = stream_dir / f"{spec.id}.wal" if spec.back_pressure == BP_SPILL else None
        pipe = StreamPipe(writer, regime=spec.back_pressure, capacity=self.ring_capacity, wal_path=wal_path)
        pipe.start()
        self._streams[spec.id] = _Stream(
            spec=spec, writer=writer, pipe=pipe, device_clock=DeviceClock(provenance),
            adapter=adapter or AdapterRef(id=spec.id, template=None),
            device=device or DeviceRef(),
        )

    def has_stream(self, stream_id: str) -> bool:
        return stream_id in self._streams

    def specs(self) -> list[StreamSpec]:
        return [st.spec for st in self._streams.values()]

    def bump_segment(self, stream_id: str) -> None:
        st = self._streams.get(stream_id)
        if st is not None:
            st.segments += 1

    # ---- ingest (the hot path) ----
    def ingest(self, packet: StreamPacket, *, to_disk: bool = True) -> None:
        """Ingest a packet. The monitor plane ALWAYS sees it (live preview, even before
        recording); the lossless disk path runs only when ``to_disk`` (i.e. while recording)."""
        st = self._streams.get(packet.stream_id)
        if st is None:
            raise KeyError(f"unknown stream {packet.stream_id!r}")
        validate_packet(packet, st.spec.timing_mode)
        recv = packet.recv_mono_ns if packet.recv_mono_ns is not None else self.clock.now_mono_ns()
        if packet.device_ts_ns is not None:
            st.device_clock.update(int(packet.device_ts_ns), recv)
        if to_disk:
            ts_s = self._session_times(st, packet, recv)
            st.pipe.submit(_Item(payload=packet.payload, ts_s=ts_s, seq=packet.seq,
                                 n_samples=packet.n_samples, t0=(ts_s[0] if ts_s else self.clock.mono_to_t(recv))))
        # monitor plane (separate, best-effort, must never break recording) — always on
        st.last_packet = packet
        with self._taps_lock:
            taps = tuple(st.taps)          # stable snapshot vs concurrent tap/untap
        for cb in taps:
            try:
                cb(packet)
            except Exception:
                pass

    def _session_times(self, st: _Stream, packet: StreamPacket, recv: int) -> Optional[list[float]]:
        dc = st.device_clock
        if packet.per_sample_ts is not None:
            return [self.clock.mono_to_t(dc.map(int(ts))) for ts in packet.per_sample_ts]
        if packet.device_ts_ns is not None:
            return [self.clock.mono_to_t(dc.map(int(packet.device_ts_ns)))]
        return [self.clock.mono_to_t(recv)]

    # ---- monitor plane ----
    def monitor_tap(self, stream_id: str, cb: Callable[[StreamPacket], None]) -> None:
        st = self._streams.get(stream_id)
        if st is None:
            return
        with self._taps_lock:
            st.taps.append(cb)

    def monitor_untap(self, stream_id: str, cb: Callable[[StreamPacket], None]) -> None:
        """Remove a previously-registered tap (e.g. when a data-plane socket closes)."""
        st = self._streams.get(stream_id)
        if st is None:
            return
        with self._taps_lock:
            try:
                st.taps.remove(cb)
            except ValueError:
                pass

    def latest(self, stream_id: str) -> Optional[StreamPacket]:
        st = self._streams.get(stream_id)
        return st.last_packet if st else None

    # ---- finalize ----
    def finalize(self) -> list[StreamEntry]:
        if self._finalized:
            raise RuntimeError("already finalized")
        self._finalized = True
        entries: list[StreamEntry] = []
        for st in self._streams.values():
            files, counts = st.pipe.stop()
            st.files, st.counts = files, counts
            # attach counted drops to the data file timing
            data_file = next((f for f in files if f.role == "data"), files[0] if files else None)
            if data_file and data_file.timing and st.pipe.drops:
                data_file.timing.drops = [
                    Drop(from_seq=d.from_seq, to_seq=d.to_seq, from_t=d.from_t, to_t=d.to_t,
                         count=d.count, reason=d.reason) for d in st.pipe.drops
                ]
            sp = st.spec
            entry = StreamEntry(
                id=sp.id, modality=sp.modality, adapter=st.adapter, device=st.device,
                schema=StreamSchema(channels=sp.channel_names, units=sp.units, dtype=sp.dtype),
                derivation=(DerivationRef(source_stream=sp.derivation.source_stream,
                                          method=sp.derivation.method, window=sp.derivation.window)
                            if sp.derivation else None),
                files=files, segments=st.segments, status="complete",
            )
            entries.append(entry)
        return entries

    def counts(self) -> dict[str, dict]:
        return {sid: st.counts for sid, st in self._streams.items()}

    def live_counts(self) -> dict[str, dict]:
        """Per-stream produced/persisted counts live (before finalize) — for previews/tests."""
        return {sid: {"produced": st.pipe._produced, "persisted": st.pipe._persisted}
                for sid, st in self._streams.items()}
