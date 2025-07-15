from abc import ABC, abstractmethod

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget


class BaseModalitySense(QWidget):
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


class BaseModalityPlay(QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # ensure the QSS background rules are honoured
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

    @abstractmethod
    def setup_ui(self):
        pass

    def start(self):
        """Called when the system starts. Can be overridden."""
        pass

    def stop(self):
        """Called when the system stops. Can be overridden."""
        pass


"""
Lightweight parent class for *offline* (post-hoc) panels.

Only responsibility: give every panel a QWidget base that
already honours QSS background rules.  It purposely omits
`start_recording()/stop_recording()` so inspection widgets
stay decoupled from the live-recording API.
"""

from abc import ABC

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QWidget


class BaseModalityEngine(QWidget):
    """
    Derive your offline panels from this class.

    ─────────────────────────────────────────────────────────────
    Convenience:
      • The constructor calls an optional `setup_ui()` method,
        so subclasses can keep their `__init__` minimal.
      • `self.window()` returns the hosting main-window
        (handy to look up `sessions_root`, etc.).
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # ensure style-sheet `background` rules are applied
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        # call optional helper implemented by subclasses
        if hasattr(self, "setup_ui"):
            try:
                self.setup_ui()  # type: ignore[attr-defined]
            except TypeError:
                # subclass did not declare setup_ui(self) – ignore
                pass

    # ----------------------------------------------------------
    @staticmethod
    def window() -> QWidget | None:
        """Return the active top-level window (if any)."""
        return QApplication.activeWindow()

    # ----------------------------------------------------------
    # Subclasses may *optionally* implement:
    #
    # def setup_ui(self):
    #     "...build widget tree here..."
    #
    # No abstract methods required for inspection-only panels.
    #
    # No abstract methods required for inspection-only panels.
    # No abstract methods required for inspection-only panels.
