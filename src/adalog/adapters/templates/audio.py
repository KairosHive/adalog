"""AudioDevice template — microphone via sounddevice (anchored, SPILL).

Captures the true ADC time (``time.inputBufferAdcTime``) in the realtime callback and emits
from there (lock-free SPILL path). RMS is monitor-only. sounddevice is lazy-imported.
"""
from __future__ import annotations

import numpy as np

from ...core.envelope import StreamPacket
from ...core.spec import BP_SPILL, ENC_WAV, TIMING_ANCHORED, Channel, StreamSpec
from ...schema.fields import IntField, StrField
from ..base import AdapterStatus, DeviceAdapter, DiscoveredSource, ST_STREAMING


class AudioDevice(DeviceAdapter):
    template_name = "audio"
    provenance = "device_portaudio"

    @staticmethod
    def config_schema():
        return {"audio": {"device": StrField("", doc="input device (blank = default)"),
                          "samplerate": IntField(48000, min=8000),
                          "channels": IntField(1, min=1, max=8),
                          "blocksize": IntField(1024, min=64)}}

    @staticmethod
    def discover():
        try:
            import sounddevice as sd
        except Exception:
            return []
        out = []
        for i, d in enumerate(sd.query_devices()):
            if d.get("max_input_channels", 0) > 0:
                out.append(DiscoveredSource(id=str(i), label=d["name"],
                                            detail={"channels": d["max_input_channels"]}))
        return out

    def resolve_streams(self):
        return [StreamSpec(id=self.info.id, modality="audio", encoding=ENC_WAV,
                           timing_mode=TIMING_ANCHORED, back_pressure=BP_SPILL,
                           sfreq_nominal=float(self._rate),
                           channels=[Channel(f"ch{i}", "", "float32") for i in range(self._channels)])]

    def _make_stream(self):
        from ..base import DeviceUnavailable, require_backend
        sd = require_backend("sounddevice", "Audio device", hint="sounddevice soundfile")
        dev = self.cfg.audio.device or None
        try:
            return sd.InputStream(samplerate=self._rate, channels=self._channels,
                                  blocksize=self.cfg.audio.blocksize, dtype="float32",
                                  device=(int(dev) if dev not in (None, "") else None), callback=self._callback)
        except Exception as exc:  # PortAudioError (native lib) / device busy / bad device
            raise DeviceUnavailable(f"Audio input could not be opened ({exc}).") from exc

    def open(self, ctx):
        super().open(ctx)
        self._rate = int(self.cfg.audio.samplerate)
        self._channels = int(self.cfg.audio.channels)
        self._seq = 0
        self._rms = 0.0
        self._stream = self._make_stream()

    def _callback(self, indata, frames, time_info, status):  # PortAudio thread (SPILL)
        adc = getattr(time_info, "inputBufferAdcTime", None)
        device_ts_ns = int(adc * 1e9) if adc else self.ctx.now_mono_ns()
        block = np.array(indata, dtype=np.float32, copy=True)
        self._rms = float(np.sqrt(np.mean(block ** 2))) if block.size else 0.0
        self.ctx.emit(StreamPacket(stream_id=self.info.id, seq=self._seq, payload=block, n_samples=frames,
                                   device_ts_ns=device_ts_ns, recv_mono_ns=self.ctx.now_mono_ns()))
        self._seq += 1

    def start(self):
        self._stream.start()

    def stop(self):
        try:
            self._stream.stop()
        except Exception:
            pass

    def close(self):
        try:
            self._stream.close()
        except Exception:
            pass

    def status(self):
        return AdapterStatus(state=ST_STREAMING, rate_est=float(self._rate), quality={"rms": self._rms})
