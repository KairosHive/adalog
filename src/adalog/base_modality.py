from PyQt6.QtWidgets import QWidget
from abc import ABC, abstractmethod


class BaseModality(QWidget):
    def __init__(self):
        super().__init__()

    @abstractmethod
    def setup_ui(self):
        pass

    def start_recording(self, session_dir):
        """Called when a session starts. Can be overridden."""
        pass

    def stop_recording(self):
        """Called when a session stops. Can be overridden."""
        pass
