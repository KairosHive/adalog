"""OSC ingest (from-scratch): logs every (address, value) to one per_sample stream.

oscpy is lazy-imported; ``_make_server`` is overridable for tests. Structured values are
stored as JSON-friendly Python (lists/scalars), not str() (fixes the old lossy CSV).
"""
from __future__ import annotations

from ...adapters.base import AdapterInfo, AdapterStatus, DeviceAdapter, ST_STREAMING
from ...core.envelope import StreamPacket
from ...core.spec import ENC_JSONL, TIMING_PER_SAMPLE, StreamSpec
from ...schema.fields import IntField, StrField


class OscAdapter(DeviceAdapter):
    info = AdapterInfo(id="osc", title="OSC", category="network")
    template_name = "osc"
    provenance = "host_arrival"

    @staticmethod
    def config_schema():
        return {"osc": {"host": StrField("0.0.0.0"), "port": IntField(8000, min=1, max=65535)}}

    def declare_streams(self):
        return [StreamSpec(id="osc", modality="osc", encoding=ENC_JSONL, timing_mode=TIMING_PER_SAMPLE)]

    def _make_server(self):
        from oscpy.server import OSCThreadServer
        srv = OSCThreadServer(advanced_matching=True)
        srv.listen(address=self.cfg.osc.host, port=int(self.cfg.osc.port), default=True)
        srv.bind(b"/*", self._on_message, get_address=True)
        return srv

    def open(self, ctx):
        super().open(ctx)
        self._seq = 0
        self._server = None

    def _decode(self, v):
        if isinstance(v, bytes):
            try:
                return v.decode("utf-8")
            except Exception:
                return list(v)
        return v

    def _on_message(self, address, *values):
        addr = address.decode("utf-8") if isinstance(address, bytes) else str(address)
        vals = [self._decode(v) for v in values]
        payload = {"address": addr, "value": (vals[0] if len(vals) == 1 else vals)}
        self.ctx.emit(StreamPacket(stream_id="osc", seq=self._seq, payload=payload,
                                   device_ts_ns=self.ctx.now_mono_ns()))
        self._seq += 1

    def start(self):
        self._server = self._make_server()

    def stop(self):
        if self._server is not None:
            try:
                self._server.stop_all()
            except Exception:
                pass

    def status(self):
        return AdapterStatus(state=ST_STREAMING)
