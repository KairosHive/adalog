"""OSC ingest (from-scratch): logs every (address, value) to one per_sample stream.

oscpy is lazy-imported; ``_make_server`` is overridable for tests. Structured values are
stored as JSON-friendly Python (lists/scalars), not str() (fixes the old lossy CSV).

Reproduces the old panel's two extras: a live message counter (``status().quality.count``)
and the ``/<store_prefix>/<name>`` sideband — messages under the configured prefix are
routed to a separate ``osc_store`` stream as ``{filename, content}`` (the old panel wrote
these straight to ``<name>.txt`` in the session; here they are captured losslessly and the
convert layer can materialise the files)."""
from __future__ import annotations

from ...adapters.base import AdapterInfo, AdapterStatus, DeviceAdapter, ST_STREAMING
from ...core.envelope import StreamPacket
from ...core.spec import ENC_JSONL, TIMING_EVENT, TIMING_PER_SAMPLE, StreamSpec
from ...schema.fields import IntField, StrField


class OscAdapter(DeviceAdapter):
    info = AdapterInfo(id="osc", title="OSC", category="network", backend="oscpy")
    template_name = "osc"
    provenance = "host_arrival"

    @staticmethod
    def config_schema():
        return {"osc": {"host": StrField("0.0.0.0"), "port": IntField(8000, min=1, max=65535)},
                "store": {"prefix": StrField("_store", doc="messages to /<prefix>/<name> are saved as files")}}

    def declare_streams(self):
        return [StreamSpec(id="osc", modality="osc", encoding=ENC_JSONL, timing_mode=TIMING_PER_SAMPLE),
                StreamSpec(id="osc_store", modality="osc", encoding=ENC_JSONL, timing_mode=TIMING_EVENT)]

    def _make_server(self):
        from ...adapters.base import DeviceUnavailable, require_backend
        require_backend("oscpy", "OSC device", hint="oscpy")
        from oscpy.server import OSCThreadServer
        srv = OSCThreadServer(advanced_matching=True)
        try:
            srv.listen(address=self.cfg.osc.host, port=int(self.cfg.osc.port), default=True)
        except OSError as exc:
            raise DeviceUnavailable(
                f"OSC: port {self.cfg.osc.port} on {self.cfg.osc.host} is unavailable ({exc}).") from exc
        # advanced_matching: a wildcard matches ONE path component, so bind /*, /*/*, …
        # to catch addresses up to 10 levels deep (e.g. /synth/freq, /muse/elements/...).
        for depth in range(1, 11):
            srv.bind(b"/*" * depth, self._on_message, get_address=True)
        return srv

    def open(self, ctx):
        super().open(ctx)
        self._seq = 0
        self._store_seq = 0
        self._count = 0
        self._server = None
        # Fail at arm (open) — not silently in the supervised start() thread — if the
        # backend is missing, so the UI gets a clean DEVICE_ERROR like every other device.
        from ...adapters.base import require_backend
        require_backend("oscpy", "OSC device", hint="oscpy")

    def _decode(self, v):
        if isinstance(v, bytes):
            try:
                return v.decode("utf-8")
            except Exception:
                return list(v)
        return v

    def _store_prefix(self) -> str:
        cfg = getattr(self, "cfg", None)
        return (cfg.store.prefix if cfg is not None else "_store").strip("/")

    def _on_message(self, address, *values):
        addr = address.decode("utf-8") if isinstance(address, bytes) else str(address)
        vals = [self._decode(v) for v in values]
        value = vals[0] if len(vals) == 1 else vals
        self._count += 1
        prefix = self._store_prefix()
        if prefix and addr.startswith(f"/{prefix}/"):
            filename = addr[len(prefix) + 2:].replace("/", "_").replace("\\", "_")
            content = "" if value is None else (value if isinstance(value, str) else str(value))
            self.ctx.emit(StreamPacket(stream_id="osc_store", seq=self._store_seq,
                                       payload={"filename": filename, "content": content},
                                       device_ts_ns=self.ctx.now_mono_ns()))
            self._store_seq += 1
            return
        self.ctx.emit(StreamPacket(stream_id="osc", seq=self._seq, payload={"address": addr, "value": value},
                                   device_ts_ns=self.ctx.now_mono_ns()))
        self._seq += 1

    def start(self):
        self._server = self._make_server()

    def stop(self):
        if self._server is not None:
            # full shutdown (stop + terminate + join) so the listener thread exits cleanly
            # instead of raising EBADF on its closed socket.
            for step in ("stop_all", "terminate_server", "join_server"):
                try:
                    getattr(self._server, step)()
                except Exception:
                    pass
            self._server = None

    def status(self):
        return AdapterStatus(state=ST_STREAMING, quality={"count": self._count})
