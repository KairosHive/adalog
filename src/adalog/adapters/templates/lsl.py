"""LSLDevice template — Lab Streaming Layer input (anchored_irregular, BACKPRESSURE).

Re-enables what goofi discards: per-sample LSL timestamps + periodic ``time_correction``.
Author fills ``default_query`` and may override ``resolve_streams`` for multi-substream
devices (e.g. Muse EEG/PPG/ACC). pylsl is lazy-imported inside methods.
"""
from __future__ import annotations

import threading
from collections import deque

import numpy as np

from ...core.envelope import StreamPacket
from ...core.spec import BP_BACKPRESSURE, ENC_ARROW, TIMING_ANCHORED_IRREGULAR, Channel, StreamSpec
from ...schema.fields import StrField
from ..base import AdapterStatus, DeviceAdapter, DiscoveredSource, ST_STALLED, ST_STREAMING


class LSLDevice(DeviceAdapter):
    template_name = "lsl"
    provenance = "device_lsl"
    pull_chunk_max = 256
    quality_window = 0   # samples of recent signal to retain for status()/quality; 0 = off

    @staticmethod
    def config_schema():
        return {"lsl": {"source": StrField("", doc="LSL source_id (blank = first match)")}}

    # ---- author hooks ----
    def default_query(self) -> dict:
        return {"source": getattr(getattr(self, "cfg", None), "lsl", None) and self.cfg.lsl.source or ""}

    def resolve_streams(self):
        return [StreamSpec(id=self.info.id, modality=self.info.category or "signal", encoding=ENC_ARROW,
                           timing_mode=TIMING_ANCHORED_IRREGULAR, back_pressure=BP_BACKPRESSURE,
                           sfreq_nominal=self._sfreq,
                           channels=[Channel(n, self._units, "float32") for n in self._ch_names])]

    # ---- discovery ----
    @staticmethod
    def discover():
        try:
            import pylsl
        except Exception:
            return []
        out = []
        for info in pylsl.resolve_streams(wait_time=0.5):
            out.append(DiscoveredSource(id=info.source_id() or info.name(), label=info.name(),
                                        detail={"type": info.type(), "channels": info.channel_count(),
                                                "srate": info.nominal_srate()}))
        return out

    # ---- transport factory (overridable in tests) ----
    def _make_inlet(self):
        from ..base import DeviceUnavailable, require_backend
        pylsl = require_backend("pylsl", "LSL device", hint="pylsl (also needs liblsl)")
        q = self.default_query()
        src = q.get("source") or ""
        streams = pylsl.resolve_streams(wait_time=1.0)
        chosen = None
        for s in streams:
            if not src or s.source_id() == src or s.name() == src:
                chosen = s
                break
        if chosen is None:
            raise DeviceUnavailable(
                f"No LSL stream{f' matching {src!r}' if src else ''} found — is the device streaming?")
        return pylsl.StreamInlet(chosen, max_chunklen=self.pull_chunk_max)

    def _inlet_info(self):
        info = self._inlet.info()
        n = info.channel_count()
        names = []
        try:
            ch = info.desc().child("channels").child("channel")
            for _ in range(n):
                names.append(ch.child_value("label") or f"ch{len(names)}")
                ch = ch.next_sibling()
        except Exception:
            pass
        if len(names) != n:
            names = [f"ch{i}" for i in range(n)]
        return names, float(info.nominal_srate() or 0.0)

    def open(self, ctx):
        super().open(ctx)
        self._running = threading.Event()
        self._inlet = self._make_inlet()
        self._ch_names, self._sfreq = self._inlet_info()
        self._units = "uV"
        self._seq = 0
        self._got = 0
        # rolling buffer of recent samples (rows = samples, cols = channels) for live
        # signal-quality in status(); auto-trims via deque maxlen. off when window == 0.
        self._recent: deque = deque(maxlen=self.quality_window or 1)

    def start(self):
        self._running.set()
        sid = self.resolve_streams()[0].id
        last_corr = 0.0
        corr = 0.0
        while self._running.is_set():
            samples, stamps = self._inlet.pull_chunk(timeout=0.2, max_samples=self.pull_chunk_max)
            if not stamps:
                continue
            now = self.ctx.now_mono_ns()
            if now - last_corr > 1_000_000_000:  # refresh time_correction ~1Hz
                try:
                    corr = self._inlet.time_correction()
                except Exception:
                    corr = 0.0
                last_corr = now
            per_sample_ts = [int((s + corr) * 1e9) for s in stamps]
            data = np.asarray(samples, dtype=np.float32)
            if self.quality_window:
                self._recent.extend(data)   # retain recent rows for quality/status
            self.ctx.emit(StreamPacket(stream_id=sid, seq=self._seq, payload=data, n_samples=len(stamps),
                                       device_ts_ns=per_sample_ts[0], recv_mono_ns=now,
                                       per_sample_ts=per_sample_ts))
            self._seq += 1
            self._got += len(stamps)

    def stop(self):
        self._running.clear()

    def close(self):
        try:
            self._inlet.close_stream()
        except Exception:
            pass

    def status(self):
        state = ST_STREAMING if self._got > 0 else ST_STALLED
        return AdapterStatus(state=state, rate_est=None)
