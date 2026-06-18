"""MIDI input (from-scratch): crash-safe NDJSON mirror of timed messages.

The .mid SMF is rebuildable from this mirror downstream; the mirror is the durable artifact.
mido is lazy-imported; ``_make_input`` is overridable for tests.
"""
from __future__ import annotations

import threading

from ...adapters.base import AdapterInfo, AdapterStatus, DeviceAdapter, DiscoveredSource, ST_STREAMING
from ...core.envelope import StreamPacket
from ...core.spec import ENC_JSONL, TIMING_PER_SAMPLE, StreamSpec
from ...schema.fields import StrField


class MidiAdapter(DeviceAdapter):
    info = AdapterInfo(id="midi", title="MIDI", category="music", multi=True, backend="mido")
    template_name = "midi"
    provenance = "host_arrival"

    @staticmethod
    def config_schema():
        return {"midi": {"port": StrField("", doc="MIDI input port (blank = first)")}}

    @staticmethod
    def discover():
        try:
            import mido
            return [DiscoveredSource(id=n, label=n) for n in mido.get_input_names()]
        except Exception:
            return []

    def declare_streams(self):
        return [StreamSpec(id="midi", modality="midi", encoding=ENC_JSONL, timing_mode=TIMING_PER_SAMPLE)]

    def _make_input(self):
        from ...adapters.base import DeviceUnavailable, require_backend
        mido = require_backend("mido", "MIDI device", hint="mido python-rtmidi")
        require_backend("rtmidi", "MIDI device", hint="python-rtmidi")  # mido's RtMidi backend
        port = self.cfg.midi.port or None
        names = mido.get_input_names()
        if port is None and names:
            port = names[0]
        if not names:
            raise DeviceUnavailable("MIDI device: no input ports found — connect a MIDI device.")
        try:
            return mido.open_input(port, callback=self._on_msg)
        except (OSError, IOError) as exc:
            raise DeviceUnavailable(f"MIDI port {port!r} could not be opened ({exc}).") from exc

    def open(self, ctx):
        super().open(ctx)
        self._seq = 0
        self._inport = self._make_input()

    def _on_msg(self, msg):
        try:
            rec = msg.dict()
        except Exception:
            rec = {"raw": str(msg)}
        self.ctx.emit(StreamPacket(stream_id="midi", seq=self._seq, payload=rec,
                                   device_ts_ns=self.ctx.now_mono_ns()))
        self._seq += 1

    def start(self):
        pass  # mido callback delivers messages

    def stop(self):
        pass

    def close(self):
        try:
            self._inport.close()
        except Exception:
            pass

    def status(self):
        return AdapterStatus(state=ST_STREAMING)
