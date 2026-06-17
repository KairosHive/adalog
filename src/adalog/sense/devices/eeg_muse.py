"""Muse / DSI EEG over LSL (anchored_irregular). Re-enables per-sample LSL timestamps."""
from __future__ import annotations

from ...adapters.base import AdapterInfo, AdapterStatus, ST_STALLED, ST_STREAMING
from ...adapters.templates import LSLDevice
from ...core.spec import ENC_ARROW, TIMING_ANCHORED_IRREGULAR, Channel, StreamSpec
from ...schema.fields import StrField


class EegMuseAdapter(LSLDevice):
    info = AdapterInfo(id="eeg_muse", title="Muse / DSI EEG (LSL)", category="neuro", multi=True)

    @staticmethod
    def config_schema():
        return {"lsl": {"source": StrField("", doc="LSL source/name (blank = first EEG stream)")}}

    def default_query(self):
        return {"source": self.cfg.lsl.source}

    def resolve_streams(self):
        return [StreamSpec(id="eeg", modality="eeg", encoding=ENC_ARROW,
                           timing_mode=TIMING_ANCHORED_IRREGULAR, sfreq_nominal=self._sfreq,
                           channels=[Channel(n, "uV", "float32") for n in self._ch_names])]

    def status(self):
        return AdapterStatus(state=ST_STREAMING if self._got else ST_STALLED, rate_est=self._sfreq)
