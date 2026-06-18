"""Muse / DSI EEG over LSL (anchored_irregular). Re-enables per-sample LSL timestamps.

Native reproduction of the old ``eeg.gfi`` headset-quality chain (no goofi): AUX channels
are stripped from the quality computation (the patch's Select-exclude list), then
:func:`adalog.core.dsp.eeg_headset_status` runs notch(60 Hz) → demean → centre → |x| →
per-channel threshold. ``status().quality`` carries the per-channel HSI codes (0/1/2) the
old ``/eeg_quality`` indicator showed. Recording stays lossless — AUX is kept on disk; only
the quality estimate excludes it, matching the original montage."""
from __future__ import annotations

import numpy as np

from ...adapters.base import AdapterInfo, AdapterStatus, ST_STALLED, ST_STREAMING
from ...adapters.templates import LSLDevice
from ...core.dsp import HSI_DISCONNECTED, eeg_headset_status
from ...core.spec import ENC_ARROW, TIMING_ANCHORED_IRREGULAR, Channel, StreamSpec
from ...schema.fields import FloatField, StrField

# AUX / reference / trigger channels excluded from quality (the eeg.gfi Select-exclude set).
_AUX_TOKENS = {"X1", "X2", "X3", "CM", "TRG"}


def _is_aux(name: str) -> bool:
    n = (name or "").strip().upper()
    if not n:
        return False
    if "AUX" in n or "ECG" in n or "TRG" in n:
        return True
    return n.rstrip(":") in _AUX_TOKENS


class EegMuseAdapter(LSLDevice):
    info = AdapterInfo(id="eeg_muse", title="Muse / DSI EEG (LSL)", category="neuro", multi=True, backend="pylsl")
    quality_window = 512   # ~2 s at 256 Hz — matches the eeg.gfi Filter buffer_size

    @staticmethod
    def config_schema():
        return {"lsl": {"source": StrField("", doc="LSL source/name (blank = first EEG stream)")},
                "quality": {
                    "threshold": FloatField(100.0, min=0.0, max=1000.0,
                                            doc="µV; centred-abs above this = bad/loose electrode"),
                    "line_freq": FloatField(60.0, min=0.0, max=120.0, doc="Notch frequency (50/60 Hz mains)"),
                }}

    def default_query(self):
        return {"source": self.cfg.lsl.source}

    def resolve_streams(self):
        return [StreamSpec(id="eeg", modality="eeg", encoding=ENC_ARROW,
                           timing_mode=TIMING_ANCHORED_IRREGULAR, sfreq_nominal=self._sfreq,
                           channels=[Channel(n, "uV", "float32") for n in self._ch_names])]

    def status(self):
        base = ST_STREAMING if self._got else ST_STALLED
        return AdapterStatus(state=base, rate_est=self._sfreq, quality=self._hsi())

    def _hsi(self) -> dict:
        names = list(self._ch_names)
        keep = [i for i, n in enumerate(names) if not _is_aux(n)]
        eeg_names = [names[i] for i in keep]
        if not self._recent or len(self._recent) < 2 or not keep:
            return {"hsi": [HSI_DISCONNECTED] * len(eeg_names), "status": HSI_DISCONNECTED,
                    "channels": eeg_names}
        buf = np.asarray(self._recent, dtype=np.float64)[:, keep]
        overall, per_ch = eeg_headset_status(
            buf, self._sfreq or 256.0,
            threshold=self.cfg.quality.threshold, line_freq=self.cfg.quality.line_freq)
        return {"hsi": per_ch, "status": overall, "channels": eeg_names}
