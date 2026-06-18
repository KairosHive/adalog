"""The sense-bridge: a tiny aiohttp server exposing control/data/status planes + the SPA.

Standalone runtime (spec §10/§11). Speaks the same WS protocol the reused frontend expects,
projecting each adapter instance as a node whose output slots are its declared streams.
No goofi runtime, no Manager, no iceoryx2 — just the RecorderService.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

import numpy as np
from aiohttp import WSMsgType, web

from ...bridge_codec import Data, encode_frame
from ...bridge_codec.codec import ARRAY, STRING
from ..service import RecorderService
from .control import dispatch
from .frontend_build import maybe_build_frontend, resolve_static_root

log = logging.getLogger("adalog.sense.bridge")


def _web_dir() -> Optional[Path]:
    """Resolve the SPA bundle to serve, rebuilding it first if stale (dev checkout)."""
    maybe_build_frontend()
    return resolve_static_root()


@web.middleware
async def _no_cache(request, handler):
    """Single-user local server: never let the browser hold stale JS/CSS across a
    `pnpm build` cycle. The negligible re-fetch cost beats serving a stale bundle."""
    resp = await handler(request)
    if isinstance(resp, web.StreamResponse):
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp


def _packet_to_data(packet) -> Data:
    payload = packet.payload
    if isinstance(payload, np.ndarray):
        return Data(ARRAY, payload.astype(np.float32, copy=False), {"shape": list(payload.shape)})
    if isinstance(payload, (bytes, bytearray)):
        return Data(STRING, "<binary>", {})
    return Data(STRING, json.dumps(payload, default=str), {})


class SenseBridge:
    def __init__(self, service: RecorderService, *, host: str = "127.0.0.1", port: int = 8137):
        self.service = service
        self.host = host
        self.port = port
        self.app = web.Application(middlewares=[_no_cache])
        self._control_sockets: set[web.WebSocketResponse] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._runner: Optional[web.AppRunner] = None
        self._setup_routes()
        self.service.add_event_listener(self._on_service_event)

    def _setup_routes(self) -> None:
        self.app.router.add_get("/api/healthz", self._healthz)
        self.app.router.add_get("/ws/control", self._control)
        self.app.router.add_get("/ws/data/{node}/{slot}", self._data)
        web_dir = _web_dir()
        if web_dir is not None:
            self.app.router.add_static("/_app", web_dir / "_app", show_index=False) if (web_dir / "_app").exists() else None
            self.app.router.add_get("/{tail:.*}", self._spa(web_dir))
        else:
            self.app.router.add_get("/", self._placeholder)

    # ---- handlers ----
    async def _healthz(self, request):
        return web.json_response({"ok": True, "app": "adalog-sense"})

    async def _placeholder(self, request):
        return web.Response(text="adalog-sense bridge is running. Frontend bundle not built.",
                            content_type="text/plain")

    def _spa(self, web_dir: Path):
        async def handler(request):
            rel = request.match_info.get("tail", "")
            target = web_dir / rel
            if rel and target.is_file():
                return web.FileResponse(target)
            return web.FileResponse(web_dir / "index.html")
        return handler

    async def _control(self, request):
        ws = web.WebSocketResponse(heartbeat=30, max_msg_size=16 * 1024 * 1024)
        await ws.prepare(request)
        self._control_sockets.add(ws)
        await ws.send_json({"event": "hello", "payload": {"app": "adalog-sense"}})
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    req = json.loads(msg.data)
                except json.JSONDecodeError:
                    await ws.send_json({"ok": False, "error": {"code": "BAD_REQUEST", "message": "bad json"}})
                    continue
                resp = await asyncio.get_event_loop().run_in_executor(None, dispatch, self.service, req)
                await ws.send_json(resp)
        finally:
            self._control_sockets.discard(ws)
        return ws

    async def _data(self, request):
        node = request.match_info["node"]
        slot = request.match_info["slot"]
        ws = web.WebSocketResponse(heartbeat=30, max_msg_size=0)
        await ws.prepare(request)
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue(maxsize=1)

        def _tap(packet):  # called from the ingest thread (monitor plane, latest-wins)
            def _put():
                if queue.full():
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                queue.put_nowait(packet)
            loop.call_soon_threadsafe(_put)

        # Bind tap + untap to the SAME core object: capture it now, so if the session is
        # swapped while this socket is open, untap still targets the core we tapped (not the
        # new session's core, which would leave an orphaned tap on the old one).
        core = None
        sess = self.service.session
        if sess is not None and sess.core.has_stream(slot):
            core = sess.core
        try:
            if core is not None:
                core.monitor_tap(slot, _tap)
            while not ws.closed:
                # poll with a timeout so a client that disconnects mid-wait is detected (the
                # socket's heartbeat flips ws.closed) instead of blocking here forever.
                try:
                    packet = await asyncio.wait_for(queue.get(), timeout=5.0)
                except asyncio.TimeoutError:
                    continue
                header = {"node_id": node, "slot_id": slot, "stream_id": packet.stream_id,
                          "seq": packet.seq, "t": 0.0, "device_ts_ns": packet.device_ts_ns,
                          "timing_mode": ""}
                await ws.send_bytes(encode_frame(header, _packet_to_data(packet)))
        except Exception:
            pass
        finally:
            if core is not None:
                core.monitor_untap(slot, _tap)  # don't leave a dead tap firing forever
        return ws

    # ---- service events -> push to control sockets ----
    def _on_service_event(self, kind: str, data: dict) -> None:
        if self._loop is None:
            return
        msg = {"event": kind, "payload": data}

        def _broadcast():
            for ws in list(self._control_sockets):
                if not ws.closed:
                    asyncio.ensure_future(ws.send_json(msg))
        self._loop.call_soon_threadsafe(_broadcast)

    # ---- lifecycle ----
    async def start(self) -> str:
        self._loop = asyncio.get_event_loop()
        self._runner = web.AppRunner(self.app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()
        url = f"http://{self.host}:{self.port}"
        log.info("adalog-sense bridge listening on %s", url)
        return url

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
