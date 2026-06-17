"""SerialDevice template — raw serial framing (per_sample/anchored_irregular, BACKPRESSURE).

Author fills ``parse(raw: bytes) -> list[dict]`` (one dict per sample) and ``resolve_streams``.
pyserial is lazy-imported; ``_make_serial`` is overridable for tests.
"""
from __future__ import annotations

import threading

from ...core.envelope import StreamPacket
from ...schema.fields import IntField, StrField
from ..base import AdapterStatus, DeviceAdapter, DiscoveredSource, ST_STREAMING


class SerialDevice(DeviceAdapter):
    template_name = "serial"
    provenance = "host_arrival"

    @staticmethod
    def config_schema():
        return {"serial": {"port": StrField("", doc="e.g. /dev/ttyUSB0 or COM5"),
                           "baud": IntField(256, min=110, max=4_000_000)}}

    @staticmethod
    def discover():
        try:
            from serial.tools import list_ports
        except Exception:
            return []
        return [DiscoveredSource(id=p.device, label=str(p)) for p in list_ports.comports()]

    # ---- author hooks ----
    def parse(self, raw: bytes) -> list[dict]:
        raise NotImplementedError

    def _make_serial(self):
        import serial
        return serial.Serial(self.cfg.serial.port, int(self.cfg.serial.baud), timeout=0.2)

    def open(self, ctx):
        super().open(ctx)
        self._running = threading.Event()
        self._serial = self._make_serial()
        self._seq = 0
        self._got = 0
        self._stream_id = self.resolve_streams()[0].id

    def start(self):
        self._running.set()
        while self._running.is_set():
            try:
                raw = self._serial.readline()
            except Exception as exc:
                self.ctx.log.warning("serial read failed: %r", exc)
                continue
            if not raw:
                continue
            for rec in self.parse(raw):
                self.ctx.emit(StreamPacket(stream_id=self._stream_id, seq=self._seq, payload=rec,
                                           device_ts_ns=self.ctx.now_mono_ns()))
                self._seq += 1
                self._got += 1

    def stop(self):
        self._running.clear()

    def close(self):
        try:
            self._serial.close()
        except Exception:
            pass

    def status(self):
        return AdapterStatus(state=ST_STREAMING, rate_est=None)
