"""Serial ECG sensor — raw single-channel time series (per_sample, host-arrival stamped).

Native reproduction of the old ``ecg.gfi`` chain (no goofi/neurokit2): a rolling buffer of
recent samples feeds :func:`adalog.core.dsp.pan_tompkins_peaks` →
:func:`adalog.core.dsp.hrv_metrics`, surfacing BPM + SDNN/SDSD/RMSSD through
``status().quality`` — the readouts the old ``/ecg_bpm`` indicator showed, plus HRV. The
sampling rate is configurable (the serial stream carries no rate metadata)."""
from __future__ import annotations

from collections import deque

import numpy as np

from ...adapters.base import AdapterInfo, AdapterStatus, ST_STALLED, ST_STREAMING
from ...adapters.templates import SerialDevice
from ...core.dsp import hrv_metrics, pan_tompkins_peaks
from ...core.spec import ENC_CSV_TS, TIMING_PER_SAMPLE, Channel, StreamSpec
from ...schema.fields import FloatField, IntField, StrField

_HRV_SECONDS = 10.0   # analysis window — long enough for a stable BPM/HRV estimate


class EcgSerialAdapter(SerialDevice):
    info = AdapterInfo(id="ecg_serial", title="Serial ECG", category="cardio", multi=True, backend="serial")

    @staticmethod
    def config_schema():
        return {"serial": {"port": StrField("", doc="e.g. /dev/ttyUSB0 or COM5"),
                           "baud": IntField(256, min=110, max=4_000_000)},
                "signal": {"sfreq": FloatField(256.0, min=1.0, max=20_000.0,
                                               doc="ECG sampling rate (Hz) — used for BPM/HRV")}}

    def _cfg_sfreq(self) -> float:
        # declare_streams() may be called before open() (catalog/tests) — tolerate no cfg.
        cfg = getattr(self, "cfg", None)
        return float(cfg.signal.sfreq) if cfg is not None else 256.0

    def open(self, ctx):
        super().open(ctx)
        self._sfreq = self._cfg_sfreq() or 256.0
        self._recent: deque = deque(maxlen=max(2, int(_HRV_SECONDS * self._sfreq)))

    def declare_streams(self):
        return [StreamSpec(id="ecg", modality="ecg", encoding=ENC_CSV_TS, timing_mode=TIMING_PER_SAMPLE,
                           sfreq_nominal=self._cfg_sfreq(), channels=[Channel("raw", "adc")])]

    def parse(self, raw: bytes) -> list[dict]:
        s = raw.strip()
        if not s:
            return []
        try:
            val: float = float(int(s))
        except ValueError:
            try:
                val = float(s)
            except ValueError:
                return []
        buf = getattr(self, "_recent", None)
        if buf is not None:
            buf.append(val)   # retain for BPM/HRV in status()
        return [{"raw": val}]

    def status(self):
        base = ST_STREAMING if self._got else ST_STALLED
        return AdapterStatus(state=base, rate_est=self._sfreq, quality=self._hrv())

    def _hrv(self) -> dict:
        if len(self._recent) < int(2 * self._sfreq):
            return {"bpm": None, "sdnn": None, "sdsd": None, "rmssd": None, "n_beats": 0}
        x = np.asarray(self._recent, dtype=np.float64)
        return hrv_metrics(pan_tompkins_peaks(x, self._sfreq), self._sfreq)
