"""Missing/failed device backends degrade to clean DEVICE_ERROR, never raw INTERNAL.

Run in the backend-free venv (or with backends monkeypatched away). These assert the
exact contract the UI relies on: ok=False, code, and an actionable message.
"""
import importlib.util
import tempfile

import pytest

from adalog.sense.bridge.control import dispatch
from adalog.sense.service import RecorderService


def _svc():
    return RecorderService(sessions_root=tempfile.mkdtemp() + "/s", include_entrypoints=False)


def _arm(svc, adapter_id):
    svc.session_create(user="t")
    return dispatch(svc, {"id": 1, "op": "device_arm", "args": {"adapter_id": adapter_id}})


NATIVE = [
    ("eeg_muse", "pylsl"),
    ("ecg_serial", "serial"),
    ("audio_mic", "sounddevice"),
    ("midi", "mido"),
    ("osc", "oscpy"),
]


@pytest.mark.parametrize("adapter_id,pkg", NATIVE)
def test_arm_without_backend_is_device_error(adapter_id, pkg):
    if importlib.util.find_spec(pkg) is not None:
        pytest.skip(f"{pkg} installed; covers the missing-backend path only")
    r = _arm(_svc(), adapter_id)
    assert r["ok"] is False
    assert r["error"]["code"] == "DEVICE_ERROR", r
    # actionable: names the package / how to install
    msg = r["error"]["message"].lower()
    assert "devices" in msg or pkg.split()[0] in msg


def test_unknown_adapter_is_not_found():
    svc = _svc()
    svc.session_create(user="t")
    r = dispatch(svc, {"id": 1, "op": "device_arm", "args": {"adapter_id": "ghost"}})
    assert r["ok"] is False and r["error"]["code"] == "NOT_FOUND"


def test_session_mutators_before_create_are_precondition():
    for op in ("session_arm", "session_start", "session_pause", "session_resume", "session_stop"):
        svc = _svc()
        r = dispatch(svc, {"id": 1, "op": op, "args": {}})
        assert r["ok"] is False and r["error"]["code"] == "PRECONDITION", (op, r)


def test_catalog_exposes_availability():
    svc = _svc()
    cat = {d["id"]: d for d in svc.list_devices()}
    # browser + network-via-requests devices are always available
    assert cat["text"]["available"] is True
    assert cat["drawing"]["available"] is True
    assert cat["meteo"]["available"] is True
    # native devices reflect find_spec of their backend
    assert cat["audio_mic"]["available"] == (importlib.util.find_spec("sounddevice") is not None)
    assert cat["eeg_muse"]["backend"] == "pylsl"


def test_internal_errors_have_no_classname_repr_leak():
    # a generic handler error should report str(exc), not repr(Exc(...))
    svc = _svc()
    svc.session_create(user="t")
    # device_configure on a missing node raises KeyError -> BAD_REQUEST (clean), not a repr
    r = dispatch(svc, {"id": 1, "op": "device_configure",
                       "args": {"node_id": "nope#0", "group": "g", "name": "n", "value": 1}})
    assert r["ok"] is False
    assert "(" not in r["error"]["message"] or "node" in r["error"]["message"].lower()


def test_text_ingest_drops_bad_items_not_batch(tmp_path):
    """A malformed item is dropped; valid items in the same batch still record."""
    from adalog.adapters.registry import AdapterRegistry
    from adalog.sense.devices import TextAdapter
    reg = AdapterRegistry(); reg.register(TextAdapter)
    svc = RecorderService(sessions_root=tmp_path / "s", registry=reg, include_entrypoints=False)
    svc.session_create(user="t")
    svc.device_arm(adapter_id="text", instance_id="0")
    svc.session_arm(); svc.session_start()
    r = svc.device_ingest(node_id="text#0", batch=[
        {"kind": "word"},                                   # missing 'word' -> dropped
        {"kind": "word", "word": "ok", "t_browser_ns": 1},  # valid
    ])
    assert r["accepted"] == 1
    svc.session_stop()


def test_drawing_ingest_bad_base64_dropped(tmp_path):
    from adalog.adapters.registry import AdapterRegistry
    from adalog.sense.devices import DrawingAdapter
    reg = AdapterRegistry(); reg.register(DrawingAdapter)
    svc = RecorderService(sessions_root=tmp_path / "s", registry=reg, include_entrypoints=False)
    svc.session_create(user="t")
    svc.device_arm(adapter_id="drawing", instance_id="0")
    svc.session_arm(); svc.session_start()
    r = svc.device_ingest(node_id="drawing#0", batch=[
        {"kind": "snapshot", "png_b64": "!!!not base64!!!"},   # dropped, no INTERNAL
        {"kind": "pen", "x": 0.1, "y": 0.2, "t_browser_ns": 1},  # valid
    ])
    assert r["accepted"] == 1
    svc.session_stop()
