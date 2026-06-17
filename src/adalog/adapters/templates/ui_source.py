"""UiSourceDevice template — the "device" is the browser (Drawing, Text).

No hardware ``open``. Samples arrive via the bridge's ``device_ingest`` RPC carrying a
browser timestamp; the Core's browser DeviceClock reconciles it to session time. Author
implements ``on_ingest(msg) -> None`` calling ``self.emit_*`` helpers. Declared
``requires="browser"`` so goofi-mode (Spec 3) marks it unavailable.
"""
from __future__ import annotations

from typing import Optional

from ...core.envelope import StreamPacket
from ..base import AdapterStatus, DeviceAdapter, ST_STREAMING


class UiSourceDevice(DeviceAdapter):
    template_name = "ui_source"
    provenance = "browser"

    def open(self, ctx):
        super().open(ctx)
        self._seq: dict[str, int] = {}

    # ---- the bridge calls this with each device_ingest message ----
    def on_ingest(self, msg: dict) -> int:
        """Parse a device_ingest payload into packets. Returns number of samples accepted."""
        batch = msg.get("batch") if isinstance(msg, dict) else None
        items = batch if batch is not None else [msg]
        accepted = 0
        for item in items:
            accepted += self.handle_item(item)
        return accepted

    # ---- author hook ----
    def handle_item(self, item: dict) -> int:
        raise NotImplementedError

    # ---- emit helpers ----
    def emit_record(self, stream_id: str, record: dict, t_browser_ns: Optional[int]) -> int:
        seq = self._seq.get(stream_id, 0)
        self.ctx.emit(StreamPacket(stream_id=stream_id, seq=seq, payload=record,
                                   device_ts_ns=t_browser_ns, recv_mono_ns=self.ctx.now_mono_ns()))
        self._seq[stream_id] = seq + 1
        return 1

    def emit_event(self, stream_id: str, record: dict, t_browser_ns: Optional[int]) -> int:
        return self.emit_record(stream_id, record, t_browser_ns)

    def start(self):
        pass  # nothing to pull; data is pushed via on_ingest

    def stop(self):
        pass

    def status(self):
        return AdapterStatus(state=ST_STREAMING)
