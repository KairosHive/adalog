"""AdapterSupervisor (spec §6.5): per-adapter isolation, restart-as-segment, stall watchdog.

Each adapter runs in its own supervised thread. An exception in one adapter is caught,
logged, and that adapter's stream(s) marked failed/degraded — every other stream keeps
recording. A watchdog flags stalls (alive but no data). Late-join and pause/resume are
fanned out generically.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field, replace
from typing import Callable, Optional

from ..core.manifest import AdapterRef, DeviceRef
from ..core.recorder.core import RecordingCore
from ..core.spec import StreamSpec
from .base import (
    ST_ERRORED_FATAL,
    ST_ERRORED_TRANSIENT,
    ST_IDLE,
    ST_PAUSED,
    ST_STALLED,
    ST_STREAMING,
    AdapterStatus,
    DeviceAdapter,
    DiscoveredSource,
)
from .context import AdapterContext


@dataclass
class Managed:
    adapter: DeviceAdapter
    instance_id: str
    node_id: str
    stream_ids: list[str] = field(default_factory=list)
    streams: list[dict] = field(default_factory=list)  # session-id'd descriptors for the UI
    thread: Optional[threading.Thread] = None
    state: str = ST_IDLE
    error: Optional[str] = None
    started: bool = False


class AdapterSupervisor:
    def __init__(self, core: RecordingCore, clock, *, on_event: Optional[Callable[[str, dict], None]] = None,
                 on_status: Optional[Callable[[Managed], None]] = None,
                 emit_fn: Optional[Callable] = None):
        self.core = core
        self.clock = clock
        self.on_event = on_event or (lambda kind, data: None)
        self.on_status = on_status or (lambda m: None)
        # All adapter emits route here. Defaults to core.ingest; the service passes a
        # state-gated sink (Session.ingest) so paused/pre-start data is dropped, not written.
        self.emit_fn = emit_fn or core.ingest
        self.managed: dict[str, Managed] = {}
        self._watchdog: Optional[threading.Thread] = None
        self._watchdog_stop = threading.Event()

    # ---- add / arm ----
    def add(self, adapter: DeviceAdapter, instance_id: str = "0", *, config: Optional[dict] = None,
            source: Optional[DiscoveredSource] = None) -> Managed:
        node_id = f"{adapter.info.id}#{instance_id}"
        m = Managed(adapter=adapter, instance_id=instance_id, node_id=node_id)
        # Map each adapter-local stream id to a session-unique id so multiple instances
        # of one adapter (hyperscanning) never collide in the RecordingCore. Instance 0
        # keeps the clean local id; later instances are suffixed with the instance id.
        id_map: dict[str, str] = {}

        def _session_id(local_id: str) -> str:
            return local_id if instance_id == "0" else f"{local_id}-{instance_id}"

        def _emit(packet) -> None:  # translate local stream id -> session stream id
            mapped = id_map.get(packet.stream_id)
            if mapped is not None and mapped != packet.stream_id:
                packet.stream_id = mapped
            self.emit_fn(packet)

        def _descriptor(spec: StreamSpec, sid: str) -> dict:
            return {"id": sid, "local_id": spec.id, "modality": spec.modality, "encoding": spec.encoding,
                    "timing_mode": spec.timing_mode, "channels": spec.channel_names}

        def _register(spec: StreamSpec) -> None:  # dynamic streams (OSC), runtime
            sid = self._add_core_stream(adapter, spec, source, _session_id(spec.id))
            id_map[spec.id] = sid
            m.stream_ids.append(sid)
            m.streams.append(_descriptor(spec, sid))
            self.on_event("slot_added", {"node_id": node_id, "slot_id": sid})

        ctx = AdapterContext(emit_fn=_emit, now_mono_ns=self.clock.now_mono_ns,
                             register_fn=_register, config=config or {}, instance_id=instance_id)
        adapter.open(ctx)
        for spec in adapter.resolve_streams():
            sid = self._add_core_stream(adapter, spec, source, _session_id(spec.id))
            id_map[spec.id] = sid
            m.stream_ids.append(sid)
            m.streams.append(_descriptor(spec, sid))
        m.state = ST_IDLE
        self.managed[node_id] = m
        return m

    def _add_core_stream(self, adapter: DeviceAdapter, spec: StreamSpec, source, session_id: str) -> str:
        """Add the stream to the core under a session-unique id; return that id."""
        spec_for_session = replace(spec, id=session_id) if session_id != spec.id else spec
        adapter_ref = AdapterRef(id=adapter.info.id, version=adapter.version, template=adapter.template_name)
        device_ref = DeviceRef(name=(source.label if source else None),
                               model=((source.detail or {}).get("model") if source and source.detail else None))
        self.core.add_stream(spec_for_session, provenance=adapter.provenance, adapter=adapter_ref, device=device_ref)
        return session_id

    # ---- start / stop ----
    def start(self, m: Managed) -> None:
        def _run():
            try:
                m.state = ST_STREAMING
                m.adapter.start()
            except Exception as exc:  # isolation: this adapter only
                m.state = ST_ERRORED_FATAL
                m.error = repr(exc)
                self.on_event("adapter_error", {"node_id": m.node_id, "code": ST_ERRORED_FATAL,
                                                "message": str(exc), "at_t": self.clock.now_s()})
                self.on_status(m)
        m.thread = threading.Thread(target=_run, name=f"adapter-{m.node_id}", daemon=True)
        m.started = True
        m.thread.start()

    def start_all(self) -> None:
        for m in self.managed.values():
            self.start(m)

    def pause_all(self) -> None:
        for m in self.managed.values():
            try:
                m.adapter.pause()
                m.state = ST_PAUSED
            except Exception:
                pass

    def resume_all(self) -> None:
        for m in self.managed.values():
            try:
                m.adapter.resume()
                m.state = ST_STREAMING
            except Exception:
                pass

    def stop_all(self, *, join_timeout: float = 5.0) -> None:
        self.stop_watchdog()
        for m in self.managed.values():
            try:
                m.adapter.stop()
            except Exception:
                pass
        for m in self.managed.values():
            if m.thread and m.thread.is_alive():
                m.thread.join(timeout=join_timeout)
            try:
                m.adapter.close()
            except Exception:
                pass
            if m.state not in (ST_ERRORED_FATAL,):
                m.state = ST_IDLE

    # ---- restart-as-segment (spec §6.5) ----
    def restart(self, m: Managed) -> None:
        try:
            m.adapter.stop()
        except Exception:
            pass
        for sid in m.stream_ids:
            self.core.bump_segment(sid)
            self.on_event("segment", {"node_id": m.node_id, "slot_id": sid, "at_t": self.clock.now_s()})
        self.start(m)

    # ---- status / watchdog ----
    def status_all(self) -> dict[str, AdapterStatus]:
        out = {}
        for node_id, m in self.managed.items():
            try:
                st = m.adapter.status()
            except Exception as exc:
                st = AdapterStatus(state=ST_ERRORED_TRANSIENT, last_error=repr(exc))
            if m.state == ST_ERRORED_FATAL:
                st.state = ST_ERRORED_FATAL
                st.last_error = m.error
            out[node_id] = st
        return out

    def start_watchdog(self, interval: float = 0.5) -> None:
        self._watchdog_stop.clear()

        def _loop():
            while not self._watchdog_stop.wait(interval):
                for node_id, st in self.status_all().items():
                    m = self.managed[node_id]
                    if st.state == ST_STALLED and m.state == ST_STREAMING:
                        self.on_event("adapter_error", {"node_id": m.node_id, "code": ST_STALLED,
                                                        "message": "no data", "at_t": self.clock.now_s()})
                    self.on_status(m)

        self._watchdog = threading.Thread(target=_loop, name="adapter-watchdog", daemon=True)
        self._watchdog.start()

    def stop_watchdog(self) -> None:
        self._watchdog_stop.set()
        if self._watchdog and self._watchdog.is_alive():
            self._watchdog.join(timeout=2.0)
