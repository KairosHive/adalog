"""Drawing capture (browser UiSource): pen-trace vectors + PNG snapshots."""
from __future__ import annotations

import base64

from ...adapters.base import AdapterInfo
from ...adapters.templates import UiSourceDevice
from ...core.envelope import StreamPacket
from ...core.spec import ENC_PENTRACE, ENC_PNG, TIMING_EVENT, TIMING_PER_SAMPLE, StreamSpec


class DrawingAdapter(UiSourceDevice):
    info = AdapterInfo(id="drawing", title="Drawing", category="human", requires="browser")

    def declare_streams(self):
        return [
            StreamSpec(id="pentrace", modality="drawing", encoding=ENC_PENTRACE, timing_mode=TIMING_PER_SAMPLE),
            StreamSpec(id="snapshot", modality="drawing", encoding=ENC_PNG, timing_mode=TIMING_EVENT),
        ]

    def handle_item(self, item: dict) -> int:
        kind = item.get("kind")
        if kind == "pen":
            return self.emit_record("pentrace", {"x": item.get("x"), "y": item.get("y"),
                                                 "pressure": item.get("pressure", 1.0),
                                                 "stroke_id": item.get("stroke_id", 0)},
                                    item.get("t_browser_ns"))
        if kind == "snapshot":
            png = base64.b64decode(item["png_b64"]) if "png_b64" in item else item.get("png", b"")
            seq = self._seq.get("snapshot", 0)
            self.ctx.emit(StreamPacket(stream_id="snapshot", seq=seq, payload=png,
                                       device_ts_ns=item.get("t_browser_ns"),
                                       recv_mono_ns=self.ctx.now_mono_ns()))
            self._seq["snapshot"] = seq + 1
            return 1
        return 0
