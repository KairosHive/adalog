"""Microphone capture (anchored WAV, true ADC time)."""
from __future__ import annotations

from ...adapters.base import AdapterInfo
from ...adapters.templates import AudioDevice


class AudioMicAdapter(AudioDevice):
    info = AdapterInfo(id="audio_mic", title="Microphone", category="audio", multi=True)
