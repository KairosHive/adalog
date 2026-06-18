"""RecorderService — the shared brain driven by both runtime modes (spec §8, §11.2).

Owns the config store, the adapter registry, and the live Session + AdapterSupervisor over
one shared RecordingCore. Exposes the control-plane operations (session_*/device_*); the
sense-bridge (standalone) and a goofi node (Spec 3) are thin transports over this object.
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Optional

from ..adapters.registry import AdapterRegistry
from ..adapters.supervisor import AdapterSupervisor
from ..core.clock import SessionClock
from ..core.config_store import ConfigStore
from ..core.manifest import Subject
from ..core.session import RECORDING, Session
from ..store.local import LocalStore
from .devices import BUILTIN

log = logging.getLogger("adalog.sense.service")


class RecorderService:
    def __init__(self, *, sessions_root: Optional[Path] = None, registry: Optional[AdapterRegistry] = None,
                 config: Optional[ConfigStore] = None, store: Optional[object] = None,
                 include_entrypoints: bool = True):
        self.config = config or ConfigStore()
        self.registry = registry or AdapterRegistry.build(BUILTIN, include_entrypoints=include_entrypoints)
        self.sessions_root = Path(sessions_root) if sessions_root else self.config.sessions_root
        self.store = store or LocalStore(self.sessions_root.parent / "adalog-store")
        self.session: Optional[Session] = None
        self.supervisor: Optional[AdapterSupervisor] = None
        self.clock: Optional[SessionClock] = None
        self._instances: dict[str, object] = {}        # node_id -> adapter
        self._event_listeners: list[Callable[[str, dict], None]] = []

    # ---- listeners (the status/telemetry plane subscribes here) ----
    def add_event_listener(self, cb: Callable[[str, dict], None]) -> None:
        self._event_listeners.append(cb)

    def _emit_event(self, kind: str, data: dict) -> None:
        for cb in list(self._event_listeners):
            try:
                cb(kind, data)
            except Exception:
                pass

    def _emit_status(self, managed) -> None:
        self._emit_event("stream_status", {"node_id": managed.node_id, "state": managed.state})

    # ---- catalog / discovery ----
    def list_devices(self) -> list[dict]:
        return self.registry.catalog()

    def discover(self, adapter_id: Optional[str] = None) -> dict[str, list[dict]]:
        ids = [adapter_id] if adapter_id else self.registry.ids()
        out: dict[str, list[dict]] = {}
        for aid in ids:
            try:
                out[aid] = [asdict(s) for s in self.registry.get(aid).discover()]
            except Exception as exc:
                log.warning("discover %s failed: %r", aid, exc)
                out[aid] = []
        return out

    # ---- session lifecycle ----
    def session_create(self, *, sessions_root=None, user: str = "u_local", subject: Optional[dict] = None,
                        label: str = "", tags: Optional[list[str]] = None, devices: Optional[list[dict]] = None) -> dict:
        if self.session is not None and self.session.state not in ("stopped",):
            raise RuntimeError("a session is already active")
        self.clock = SessionClock()
        subj = Subject(**subject) if subject else Subject(id=user)
        self.session = Session.create(sessions_root or self.sessions_root, user=user, subject=subj,
                                      label=label, tags=tags, clock=self.clock)
        self.supervisor = AdapterSupervisor(self.session.core, self.clock, on_event=self._emit_event,
                                            on_status=self._emit_status, emit_fn=self.session.ingest)
        self._instances.clear()
        for d in (devices or []):
            self.device_arm(**d)
        return {"session_id": self.session.session_id, "state": self.session.state}

    def device_arm(self, *, adapter_id: str, instance_id: str = "0", source_id: Optional[str] = None,
                   config: Optional[dict] = None) -> dict:
        cls = self.registry.get(adapter_id)
        adapter = cls()
        source = None
        if source_id:
            for s in cls.discover():
                if s.id == source_id:
                    source = s
                    break
        m = self.supervisor.add(adapter, instance_id, config=config or {}, source=source)
        self._instances[m.node_id] = adapter
        return {"instance_id": instance_id, "node_id": m.node_id, "streams": m.streams}

    def session_arm(self) -> dict:
        self.session.commit_draft()
        return {"state": self.session.state,
                "devices": [{"node_id": nid, "state": m.state} for nid, m in self.supervisor.managed.items()]}

    def session_start(self) -> dict:
        self.session.start()
        self.supervisor.start_all()
        self.supervisor.start_watchdog(interval=0.5)
        return {"state": "recording", "t0_utc_ns": self.clock.t0_utc_ns}

    def device_ingest(self, *, node_id: str, batch: list[dict]) -> dict:
        # Recording-state gating (spec §11.4): drop + count when not recording / paused.
        if self.session is None or self.session.state != RECORDING:
            return {"accepted": 0, "dropped": len(batch)}
        adapter = self._instances.get(node_id)
        if adapter is None or not hasattr(adapter, "on_ingest"):
            return {"accepted": 0, "dropped": len(batch), "error": "no such ui-source node"}
        accepted = adapter.on_ingest({"batch": batch})
        return {"accepted": int(accepted), "dropped": len(batch) - int(accepted)}

    def session_pause(self) -> dict:
        self.supervisor.pause_all()
        self.session.pause()
        return {"state": self.session.state, "at_t": self.clock.now_s()}

    def session_resume(self) -> dict:
        self.session.resume()
        self.supervisor.resume_all()
        return {"state": self.session.state, "at_t": self.clock.now_s()}

    def session_stop(self, *, publish: bool = False) -> dict:
        self.supervisor.stop_all()
        manifest = self.session.stop()
        # persist last-used device set + subject defaults for next launch
        self.config.set_last_used_devices(list(self.supervisor.managed.keys()))
        if publish:
            try:
                self.store.publish_session(self.session.dir)
            except Exception as exc:
                log.warning("publish failed: %r", exc)
        return {"state": "complete", "manifest_path": str(self.session.dir / "manifest.json"),
                "duration_s": manifest.duration_s, "session_id": manifest.session_id}

    # ---- status / monitor plane ----
    def status(self) -> dict:
        if self.supervisor is None:
            return {"state": "idle", "streams": []}
        streams = []
        for node_id, st in self.supervisor.status_all().items():
            streams.append({"node_id": node_id, "state": st.state, "rate_est": st.rate_est,
                            "quality": st.quality, "last_error": st.last_error})
        return {"state": (self.session.state if self.session else "idle"), "streams": streams}

    def monitor_tap(self, stream_id: str, cb) -> None:
        self.session.core.monitor_tap(stream_id, cb)
