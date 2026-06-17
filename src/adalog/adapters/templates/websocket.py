"""WebSocketDevice template — subscribe to a streaming WS API (per_sample, SPILL).

Author fills ``on_message(data) -> list[dict]`` and ``resolve_streams``. Uses aiohttp (a core
dep) in a private event loop thread with reconnect.
"""
from __future__ import annotations

import asyncio
import threading

from ...core.envelope import StreamPacket
from ...schema.fields import StrField
from ..base import AdapterStatus, DeviceAdapter, ST_STREAMING


class WebSocketDevice(DeviceAdapter):
    template_name = "websocket"
    provenance = "host_arrival"

    @staticmethod
    def config_schema():
        return {"ws": {"url": StrField("", doc="ws:// or wss:// endpoint")}}

    # ---- author hook ----
    def on_message(self, data) -> list[dict]:
        raise NotImplementedError

    def open(self, ctx):
        super().open(ctx)
        self._stop = threading.Event()
        self._thread = None
        self._seq = 0
        self._stream_id = self.resolve_streams()[0].id

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=f"ws-{self.info.id}", daemon=True)
        self._thread.start()

    def _run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._consume())
        finally:
            loop.close()

    async def _consume(self):
        import aiohttp
        url = self.cfg.ws.url
        while not self._stop.is_set():
            try:
                async with aiohttp.ClientSession() as sess:
                    async with sess.ws_connect(url, heartbeat=30) as ws:
                        async for msg in ws:
                            if self._stop.is_set():
                                break
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                data = msg.data
                            elif msg.type == aiohttp.WSMsgType.BINARY:
                                data = msg.data
                            else:
                                continue
                            for rec in self.on_message(data):
                                self.ctx.emit(StreamPacket(stream_id=self._stream_id, seq=self._seq,
                                                           payload=rec, device_ts_ns=self.ctx.now_mono_ns()))
                                self._seq += 1
            except Exception as exc:
                self.ctx.log.warning("ws error: %r (reconnecting)", exc)
                await asyncio.sleep(1.0)

    def stop(self):
        self._stop.set()

    def status(self):
        return AdapterStatus(state=ST_STREAMING)
