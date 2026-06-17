"""Built-in device adapters for adalog-sense. BUILTIN is merged with entry-points by the service."""
from .audio_mic import AudioMicAdapter
from .drawing import DrawingAdapter
from .ecg_serial import EcgSerialAdapter
from .eeg_muse import EegMuseAdapter
from .meteo import MeteoAdapter
from .midi import MidiAdapter
from .osc import OscAdapter
from .text import TextAdapter

BUILTIN = [
    EegMuseAdapter, EcgSerialAdapter, AudioMicAdapter, DrawingAdapter,
    TextAdapter, MidiAdapter, OscAdapter, MeteoAdapter,
]

__all__ = ["BUILTIN"] + [c.__name__ for c in BUILTIN]
