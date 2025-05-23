from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget
from abc import ABC, abstractmethod


class BaseModality(QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # ensure the QSS background rules are honoured
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

    @abstractmethod
    def setup_ui(self):
        pass

    def start_recording(self, session_dir):
        """Called when a session starts. Can be overridden."""
        pass

    def stop_recording(self):
        """Called when a session stops. Can be overridden."""
        pass
