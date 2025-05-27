from __future__ import annotations

"""Adalog Drawing modality panel

Place this file in ``adalog/modalities/``.  It exposes a ``Drawing`` class that
is automatically loaded by the main Adalog interface (the file name --> class
name convention is already handled in ``MainWindow.load_modalities``).

The panel lets participants sketch on a canvas while a session is running.  At
each pen‑lift (end of a stroke) the current image is saved as a PNG inside
``<session_dir>/drawings/`` and an entry is appended to ``drawings.csv`` with
its timestamp.

The panel follows the same life‑cycle hooks as the other modalities:
``start_recording(session_dir)`` and ``stop_recording()``.
"""

from datetime import datetime
import os
from pathlib import Path

import pandas as pd
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QImage, QMouseEvent, QPainter, QPen, QColor, QPixmap, QResizeEvent
from PyQt6.QtWidgets import (
    QColorDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QSlider,
)

from adalog.base_modality import BaseModality


# ──────────────────────────────────────────────────────────────────────────────
# Canvas widget
# ──────────────────────────────────────────────────────────────────────────────
class DrawingCanvas(QLabel):
    """Simple QWidget that records free‑hand drawings."""

    strokeFinished = pyqtSignal()  # emitted every time the mouse button is released

    def __init__(self, parent=None):
        super().__init__(parent)
        self.penColor: QColor = QColor("black")
        self.penWidth: int = 2
        self._drawing = False
        self._last_point = None
        self.setMinimumSize(300, 200)
        self._init_image(self.size())

    def _init_image(self, size: QSize):
        self.image = QImage(size, QImage.Format.Format_RGB32)
        self.image.fill(Qt.GlobalColor.white)
        self.setPixmap(QPixmap.fromImage(self.image))

    def clear(self):
        self.image.fill(Qt.GlobalColor.white)
        self.setPixmap(QPixmap.fromImage(self.image))

    def resizeEvent(self, event: QResizeEvent):
        new_size = event.size()
        if new_size != self.image.size():
            new_image = QImage(new_size, QImage.Format.Format_RGB32)
            new_image.fill(Qt.GlobalColor.white)
            painter = QPainter(new_image)
            painter.drawImage(0, 0, self.image)
            self.image = new_image
            self.setPixmap(QPixmap.fromImage(self.image))
        super().resizeEvent(event)

    def mousePressEvent(self, e: QMouseEvent):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drawing = True
            self._last_point = e.position().toPoint()

    def mouseMoveEvent(self, e: QMouseEvent):
        if self._drawing:
            painter = QPainter(self.image)
            pen = QPen(self.penColor, self.penWidth, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(self._last_point, e.position().toPoint())
            self._last_point = e.position().toPoint()
            self.setPixmap(QPixmap.fromImage(self.image))

    def mouseReleaseEvent(self, e: QMouseEvent):
        if self._drawing and e.button() == Qt.MouseButton.LeftButton:
            self._drawing = False
            self.strokeFinished.emit()


# ──────────────────────────────────────────────────────────────────────────────
# Panel class
# ──────────────────────────────────────────────────────────────────────────────
class Drawing(BaseModality):
    """Dockable Drawing panel for Adalog."""

    def __init__(self):
        super().__init__()
        self.recording: bool = False
        self.session_dir: str | None = None

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout()

        self.canvas = DrawingCanvas()
        self.canvas.strokeFinished.connect(self._save_current_stroke)
        layout.addWidget(self.canvas)

        controls = QHBoxLayout()

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.canvas.clear)
        controls.addWidget(self.clear_btn)

        self.color_btn = QPushButton("Pen Color")
        self.color_btn.clicked.connect(self._choose_color)
        controls.addWidget(self.color_btn)

        controls.addWidget(QLabel("Pen Size:"))
        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(1, 30)
        self.size_slider.setValue(2)
        self.size_slider.valueChanged.connect(self._update_pen_width)
        controls.addWidget(self.size_slider)

        controls.addStretch()
        layout.addLayout(controls)

        self.setLayout(layout)

    def _choose_color(self):
        color = QColorDialog.getColor(initial=self.canvas.penColor, parent=self)
        if color.isValid():
            self.canvas.penColor = color
            self.color_btn.setStyleSheet(f"background-color: {color.name()};")

    def _update_pen_width(self, value: int):
        self.canvas.penWidth = value

    def start_recording(self, session_dir: str):
        self.session_dir = session_dir
        self.recording = True
        self.canvas.clear()

        drawings_dir = Path(session_dir)
        drawings_dir.mkdir(exist_ok=True)

        csv_path = drawings_dir / "drawings.csv"
        if not csv_path.exists():
            pd.DataFrame(columns=["timestamp", "filename"]).to_csv(csv_path, index=False)

    def stop_recording(self):
        self.recording = False
        self.session_dir = None

    def _save_current_stroke(self):
        if not (self.recording and self.session_dir):
            return

        drawings_dir = Path(self.session_dir)
        drawings_dir.mkdir(exist_ok=True)

        ts = datetime.utcnow().isoformat().replace(":", "-").replace(".", "-")
        filename = f"{ts}.png"
        full_path = drawings_dir / filename
        self.canvas.image.save(str(full_path))

        csv_path = drawings_dir / "drawings.csv"
        pd.DataFrame([[ts, filename]], columns=["timestamp", "filename"]).to_csv(csv_path, mode="a", header=False, index=False)
