"""Bridge tests: headless op-registry conformance + live aiohttp control/data WS."""
import asyncio
import json

import aiohttp
import pytest

from adalog.adapters.registry import AdapterRegistry
from adalog.core.config_store import ConfigStore
from adalog.sense.bridge.control import dispatch
from adalog.sense.bridge.server import SenseBridge
from adalog.sense.devices import TextAdapter
from adalog.sense.service import RecorderService
from adalog.store.local import LocalStore


def _service(tmp_path):
    reg = AdapterRegistry()
    reg.register_all([TextAdapter])
    return RecorderService(sessions_root=tmp_path / "sessions", registry=reg,
                           config=ConfigStore(tmp_path / "config.json"),
                           store=LocalStore(tmp_path / "store"), include_entrypoints=False)


# ---- headless op-registry conformance (milestone 8a) ----
def test_dispatch_full_session_lifecycle(tmp_path):
    svc = _service(tmp_path)

    def call(op, **args):
        return dispatch(svc, {"id": op, "op": op, "args": args})

    assert call("ping")["result"] == {"pong": True}
    assert {d["id"] for d in call("list_devices")["result"]["devices"]} == {"text"}

    r = call("session_create", user="u_test", label="x", tags=["t"])
    assert r["ok"] and r["result"]["state"] == "created"
    arm = call("device_arm", adapter_id="text", instance_id="0")
    assert arm["result"]["node_id"] == "text#0"
    assert call("session_arm")["result"]["state"] == "armed"
    assert call("session_start")["result"]["state"] == "recording"
    ing = call("device_ingest", node_id="text#0", batch=[{"kind": "word", "word": "hi", "t_browser_ns": 1}])
    assert ing["result"]["accepted"] == 1
    stop = call("session_stop")
    assert stop["result"]["state"] == "complete"


def test_dispatch_errors_are_normalized(tmp_path):
    svc = _service(tmp_path)
    bad = dispatch(svc, {"id": 1, "op": "nope", "args": {}})
    assert bad["ok"] is False and bad["error"]["code"] == "BAD_REQUEST"
    # precondition: start before create
    pre = dispatch(svc, {"id": 2, "op": "session_start", "args": {}})
    assert pre["ok"] is False and pre["error"]["code"] in ("PRECONDITION", "INTERNAL")


# ---- live aiohttp control + data WS ----
@pytest.mark.asyncio
async def test_live_control_ws(tmp_path, aiohttp_unused_port=None):
    svc = _service(tmp_path)
    port = 8231
    bridge = SenseBridge(svc, host="127.0.0.1", port=port)
    await bridge.start()
    try:
        async with aiohttp.ClientSession() as cs:
            # health
            async with cs.get(f"http://127.0.0.1:{port}/api/healthz") as resp:
                assert (await resp.json())["ok"] is True
            async with cs.ws_connect(f"http://127.0.0.1:{port}/ws/control") as ws:
                hello = await ws.receive_json()
                assert hello["event"] == "hello"
                await ws.send_json({"id": "a", "op": "ping", "args": {}})
                resp = await ws.receive_json()
                assert resp["ok"] and resp["result"] == {"pong": True}
                await ws.send_json({"id": "b", "op": "session_create", "args": {"user": "u_test"}})
                r = await ws.receive_json()
                assert r["result"]["state"] == "created"
    finally:
        await bridge.stop()
