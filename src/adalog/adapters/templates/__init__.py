"""Device-adapter templates: transport + timing + back-pressure presets."""
from .audio import AudioDevice
from .lsl import LSLDevice
from .rest_poll import RestPollDevice
from .serial import SerialDevice
from .ui_source import UiSourceDevice
from .websocket import WebSocketDevice

__all__ = ["AudioDevice", "LSLDevice", "RestPollDevice", "SerialDevice", "UiSourceDevice", "WebSocketDevice"]
