"""OSC end-to-end capture over a real oscpy server: multi-level addresses must be caught
(the wildcard binding must cover several nesting depths) and the store sideband routed."""
import importlib.util
import time

import pytest

if importlib.util.find_spec("oscpy") is None:
    pytest.skip("oscpy not installed", allow_module_level=True)

# NOTE: oscpy's listener thread can raise EBADF on its socket during server teardown — a
# benign shutdown race inside the library. It surfaces as a PytestUnhandledThreadException
# warning, narrowly silenced in pyproject's filterwarnings (matched on _run_listener).

from adalog.adapters.context import AdapterContext
from adalog.sense.devices.osc import OscAdapter


def _free_port():
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_osc_captures_multilevel_addresses_and_store():
    emitted = []
    port = _free_port()
    a = OscAdapter()
    a.open(AdapterContext(emit_fn=emitted.append, now_mono_ns=lambda: 1,
                          config={"osc": {"host": "127.0.0.1", "port": port}}))
    a.start()
    try:
        time.sleep(0.2)
        from oscpy.client import OSCClient
        cli = OSCClient("127.0.0.1", port)
        cli.send_message(b"/freq", [1.0])               # 1 level
        cli.send_message(b"/synth/freq", [440.0])       # 2 levels — the regressed case
        cli.send_message(b"/a/b/c", [7])                # 3 levels
        cli.send_message(b"/_store/notes", [b"hello"])  # store sideband
        time.sleep(0.5)
    finally:
        a.stop()

    logged = [p for p in emitted if p.stream_id == "osc"]
    stored = [p for p in emitted if p.stream_id == "osc_store"]
    addrs = {p.payload["address"] for p in logged}
    assert {"/freq", "/synth/freq", "/a/b/c"} <= addrs, f"missed multi-level addresses: {addrs}"
    assert len(stored) == 1 and stored[0].payload == {"filename": "notes", "content": "hello"}
    assert a._count == 4
