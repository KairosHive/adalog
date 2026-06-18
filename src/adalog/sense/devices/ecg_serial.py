"""Serial ECG sensor — raw single-channel time series (per_sample, host-arrival stamped)."""
from __future__ import annotations

from ...adapters.base import AdapterInfo
from ...adapters.templates import SerialDevice
from ...core.spec import ENC_CSV_TS, TIMING_PER_SAMPLE, Channel, StreamSpec
from ...schema.fields import IntField, StrField


class EcgSerialAdapter(SerialDevice):
    info = AdapterInfo(id="ecg_serial", title="Serial ECG", category="cardio", multi=True)

    @staticmethod
    def config_schema():
        return {"serial": {"port": StrField("", doc="e.g. /dev/ttyUSB0 or COM5"),
                           "baud": IntField(256, min=110, max=4_000_000)}}

    def declare_streams(self):
        return [StreamSpec(id="ecg", modality="ecg", encoding=ENC_CSV_TS, timing_mode=TIMING_PER_SAMPLE,
                           channels=[Channel("raw", "adc")])]

    def parse(self, raw: bytes) -> list[dict]:
        s = raw.strip()
        if not s:
            return []
        try:
            return [{"raw": int(s)}]
        except ValueError:
            try:
                return [{"raw": float(s)}]
            except ValueError:
                return []
