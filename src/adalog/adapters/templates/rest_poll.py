"""RestPollDevice template — poll a REST/HTTP API on an interval (per_sample, BLOCK).

Author fills ``declare_streams`` + ``fetch() -> list[dict]`` (newest rows). The template
runs the loop, dedupes by a key, stamps host-arrival time, and emits one record per row.
"""
from __future__ import annotations

import threading
import time
from typing import Optional

from ...core.spec import BP_BLOCK, TIMING_PER_SAMPLE, StreamSpec
from ...schema.fields import FloatField
from ..base import AdapterStatus, DeviceAdapter, ST_STREAMING


class RestPollDevice(DeviceAdapter):
    template_name = "rest_poll"
    provenance = "host_arrival"
    default_interval_s = 10.0

    @staticmethod
    def config_schema():
        return {"poll": {"interval_s": FloatField(RestPollDevice.default_interval_s, min=0.1, doc="seconds")}}

    # ---- author hooks ----
    def fetch(self) -> list[dict]:
        raise NotImplementedError

    def dedup_key(self, record: dict):
        return None  # None => never deduped

    # ---- template machinery ----
    def open(self, ctx):
        super().open(ctx)
        self._running = threading.Event()
        self._seen = None
        self._seq = 0
        self._emitted = 0
        specs = self.resolve_streams()
        self._stream_id = specs[0].id if specs else self.info.id

    def start(self):
        self._running.set()
        interval = float(getattr(getattr(self.cfg, "poll", None), "interval_s", self.default_interval_s))
        while self._running.is_set():
            try:
                for rec in self.fetch():
                    key = self.dedup_key(rec)
                    if key is not None and key == self._seen:
                        continue
                    if key is not None:
                        self._seen = key
                    self.emit_record(rec)
            except Exception as exc:  # surface, keep polling
                self.ctx.log.warning("poll failed: %r", exc)
            self._running.wait(interval)

    def emit_record(self, record: dict):
        from ...core.envelope import StreamPacket
        self.ctx.emit(StreamPacket(stream_id=self._stream_id, seq=self._seq, payload=record,
                                   device_ts_ns=self.ctx.now_mono_ns()))
        self._seq += 1
        self._emitted += 1

    def stop(self):
        self._running.clear()

    def status(self):
        return AdapterStatus(state=ST_STREAMING, rate_est=None)

    def _default_spec(self, channels, **kw) -> StreamSpec:
        return StreamSpec(id=self.info.id, modality=self.info.category or "data",
                          encoding="csv_ts", timing_mode=TIMING_PER_SAMPLE, back_pressure=BP_BLOCK,
                          channels=channels, **kw)
