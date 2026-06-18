"""Control-plane op-registry (spec §11.2).

Maps op names to RecorderService methods and normalizes responses/errors. This is the
fixture-able conformance contract the frontend (and Spec 3) speaks.
"""
from __future__ import annotations

from typing import Any, Callable

from ...adapters.base import DeviceUnavailable
from ..service import RecorderService, UnknownAdapter

Handler = Callable[[RecorderService, dict], Any]


def _layout_get(svc: RecorderService, a: dict):
    return {"layout": svc.config.get_app("window_layout")}


def _layout_set(svc: RecorderService, a: dict):
    svc.config.set_app("window_layout", a.get("layout"))
    return {"ok": True}


OPS: dict[str, Handler] = {
    "ping": lambda svc, a: {"pong": True},
    "list_devices": lambda svc, a: {"devices": svc.list_devices()},
    "device_discover": lambda svc, a: {"sources": svc.discover(a.get("adapter_id"))},
    "session_create": lambda svc, a: svc.session_create(
        sessions_root=a.get("sessions_root"), user=a.get("user", "u_local"), subject=a.get("subject"),
        label=a.get("label", ""), tags=a.get("tags"), devices=a.get("devices")),
    "device_arm": lambda svc, a: svc.device_arm(adapter_id=a["adapter_id"], instance_id=a.get("instance_id", "0"),
                                                source_id=a.get("source_id"), config=a.get("config")),
    "device_configure": lambda svc, a: _device_configure(svc, a),
    "session_arm": lambda svc, a: svc.session_arm(),
    "session_start": lambda svc, a: svc.session_start(),
    "session_pause": lambda svc, a: svc.session_pause(),
    "session_resume": lambda svc, a: svc.session_resume(),
    "session_stop": lambda svc, a: svc.session_stop(publish=a.get("publish", False)),
    "device_ingest": lambda svc, a: svc.device_ingest(node_id=a["node_id"], batch=a.get("batch", [])),
    "status": lambda svc, a: svc.status(),
    "layout_get": _layout_get,
    "layout_set": _layout_set,
}


def _device_configure(svc: RecorderService, a: dict):
    adapter = svc._instances.get(a["node_id"])
    if adapter is None:
        raise KeyError(f"no node {a['node_id']!r}")
    res = adapter.reconfigure(a["group"], a["name"], a["value"])
    return {"applied": res.applied, "requires_segment": res.requires_segment, "message": res.message}


def dispatch(svc: RecorderService, msg: dict) -> dict:
    rid = msg.get("id")
    op = msg.get("op")
    args = msg.get("args") or {}
    handler = OPS.get(op)
    if handler is None:
        return {"id": rid, "ok": False, "error": {"code": "BAD_REQUEST", "message": f"unknown op {op!r}"}}
    try:
        result = handler(svc, args)
        return {"id": rid, "ok": True, "result": result}
    except DeviceUnavailable as exc:           # missing backend / device absent or busy
        return {"id": rid, "ok": False, "error": {"code": "DEVICE_ERROR", "message": str(exc)}}
    except UnknownAdapter as exc:              # no such device id
        return {"id": rid, "ok": False, "error": {"code": "NOT_FOUND", "message": str(exc)}}
    except KeyError as exc:
        return {"id": rid, "ok": False, "error": {"code": "BAD_REQUEST", "message": str(exc)}}
    except RuntimeError as exc:                # precondition (no session, wrong state, …)
        return {"id": rid, "ok": False, "error": {"code": "PRECONDITION", "message": str(exc)}}
    except Exception as exc:                   # genuine bug — clean message, no class-name repr leak
        return {"id": rid, "ok": False, "error": {"code": "INTERNAL", "message": str(exc) or type(exc).__name__}}
