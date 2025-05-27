# adalog/modalities/meteo.py
"""
Meteo panel for Adalog
────────────────────────────────────────────────────────
• Polls NOAA SWPC every 10 s for magnetic-field (MAG) and
  solar-wind (PLASMA) data.
• Shows 5 round gauges (speedometer style) for
  Bz, Bt, Wind-speed, Proton-density, Plasma-temperature.
• While a session is running, every fresh sample is appended to
  <session-dir>/meteo.csv with both NOAA’s `time_tag`
  and the local UTC collection timestamp.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from math import cos, pi, sin
from pathlib import Path

import pandas as pd
import requests
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QLabel,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from adalog.base_modality import BaseModality


# ════════════════════════════════════════════════════════════════════
#  Generic gauge widget
# ════════════════════════════════════════════════════════════════════
@dataclass
class RangeDef:
    mn: float
    mx: float
    green: float  # upper bound of green zone
    orange: float  # upper bound of orange zone (optional – set None
    # if you want only green + red)


class GaugeWidget(QWidget):

    def __init__(self, unit: str, rng: RangeDef, parent=None):
        super().__init__(parent)
        self._unit, self._rng = unit, rng
        self._val = rng.mn
        self.setMinimumSize(130, 130)

    # public ---------------------------------------------------------
    def set_value(self, v: float):
        self._val = max(self._rng.mn, min(self._rng.mx, float(v)))
        self.update()

    # helpers --------------------------------------------------------
    def _angle(self, v: float) -> int:
        """Map value → QPainter angle (degrees*16)."""
        frac = (v - self._rng.mn) / (self._rng.mx - self._rng.mn)
        deg = 225 - frac * 270  # 225° (left-down) →  -45° (right-down)
        return int(deg * 16)

    def _draw_arc(self, p: QPainter, start_v: float, end_v: float, colour: str, r: float, w: float):
        pen = QPen(QColor(colour), w, cap=Qt.PenCapStyle.FlatCap)
        p.setPen(pen)
        start_ang = self._angle(start_v)
        span_ang = self._angle(end_v) - start_ang  # negative → clockwise
        p.drawArc(int(self.width() / 2 - r), int(self.height() / 2 - r), int(2 * r), int(2 * r), start_ang, span_ang)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing)

        cx, cy = self.width() / 2, self.height() / 2
        radius = min(self.width(), self.height()) * 0.42
        bar_w = radius * 0.15

        # Color zones
        self._draw_arc(p, self._rng.mn, self._rng.green, "#65a765", radius, bar_w)
        if self._rng.orange is not None:
            self._draw_arc(p, self._rng.green, self._rng.orange, "#e5b761", radius, bar_w)
            self._draw_arc(p, self._rng.orange, self._rng.mx, "#c45858", radius, bar_w)
        else:
            self._draw_arc(p, self._rng.green, self._rng.mx, "#bb5858", radius, bar_w)

        # Needle
        p.setPen(QPen(Qt.GlobalColor.white, 2))
        ang = 225 - (self._val - self._rng.mn) / (self._rng.mx - self._rng.mn) * 270
        ang_r = pi * ang / 180
        p.drawLine(int(cx), int(cy), int(cx + cos(ang_r) * radius * 0.85), int(cy - sin(ang_r) * radius * 0.85))

        # Value (a bit lower than center)
        p.setPen(Qt.GlobalColor.white)
        p.setFont(QFont("Segoe UI", int(radius * 0.30)))
        value_rect = self.rect().adjusted(0, int(radius * 1.9), 0, 0)  # shift downward
        p.drawText(value_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, f"{self._val:.2f}")

        # Larger unit (under value)
        unit_font = QFont("Segoe UI", int(radius * 0.25))
        p.setFont(unit_font)
        unit_rect = self.rect().adjusted(0, int(radius * 0.45), 0, 0)  # even further down
        p.drawText(unit_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self._unit)


# ════════════════════════════════════════════════════════════════════
#  NOAA URLs & column maps
# ════════════════════════════════════════════════════════════════════
_MAG_URL = "https://services.swpc.noaa.gov/products/solar-wind/mag-1-day.json"
_PLASMA_URL = "https://services.swpc.noaa.gov/products/solar-wind/plasma-1-day.json"

_COL_RENAME_MAG = {
    "bx_gsm": "Bx_GSM_nT",
    "by_gsm": "By_GSM_nT",
    "bz_gsm": "Bz_GSM_nT",
    "bt": "Mag_Field_Total_nT",
}
_COL_RENAME_PLASMA = {
    "density": "Proton_Density_per_cm3",
    "speed": "Solar_Wind_Speed_kmps",
    "temperature": "Plasma_Temperature_K",
}

# Gauge ranges (edit if you like)
R_BZ = RangeDef(-5, 5, 0, 2)  # green ≤5, orange 0..-5, red <-10
R_BT = RangeDef(0, 20, 10, 15)
R_SPD = RangeDef(300, 600, 450, 500)
R_DEN = RangeDef(0, 10, 5, 8)
R_TEMP = RangeDef(0, 500_000, 2e5, 2.5e5)


# ════════════════════════════════════════════════════════════════════
#  Main panel
# ════════════════════════════════════════════════════════════════════
class Meteo(BaseModality, QWidget):
    """Solar-wind & geomagnetic-activity panel with gauges."""

    _POLL_MS = 10_000  # 10 s

    def __init__(self):
        super().__init__()
        self.session_dir: str | None = None
        self._csv_path: Path | None = None
        self.recording = False
        self._last_time_tag: pd.Timestamp | None = None
        self._lock = threading.Lock()

        self._build_ui()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(self._POLL_MS)

    # ------------------------- UI -----------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        gauges_row = QHBoxLayout()

        def wrap_gauge(title: str, widget: GaugeWidget):
            box = QVBoxLayout()
            label = QLabel(title)
            label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            label.setStyleSheet("color: white; font-size: 14px;")
            box.addWidget(label)
            box.addWidget(widget)
            return box

        self._g_bz = GaugeWidget("nT", R_BZ)
        self._g_bt = GaugeWidget("nT", R_BT)
        self._g_spd = GaugeWidget("km/s", R_SPD)
        self._g_den = GaugeWidget("#/cm³", R_DEN)
        self._g_tmp = GaugeWidget("K", R_TEMP)

        for layout in (
            wrap_gauge("Earth Mag. Field (Bz)", self._g_bz),
            wrap_gauge("Earth Mag. Field (Total)", self._g_bt),
            wrap_gauge("Solar Wind Speed", self._g_spd),
            wrap_gauge("Proton Density", self._g_den),
            wrap_gauge("Plasma Temp", self._g_tmp),
        ):
            gauges_row.addLayout(layout)

        root.addLayout(gauges_row)

        self._lbl_updated = QLabel("Last update: ––:––:––")
        self._lbl_updated.setAlignment(Qt.AlignmentFlag.AlignRight)
        root.addWidget(self._lbl_updated)
        root.addStretch()

    # --------------------- session hooks ----------------------------
    def start_recording(self, session_dir: str):
        self.session_dir = session_dir
        self._csv_path = Path(session_dir) / "meteo.csv"
        self.recording = True

    def stop_recording(self):
        self.recording = False
        self.session_dir = None
        self._csv_path = None

    # --------------------- periodic poll ----------------------------
    def _poll(self):
        if not self._lock.acquire(blocking=False):
            return
        try:
            row = self._latest_row()
            if row is None:
                return

            t_tag = row["time_tag"]
            if self._last_time_tag is not None and t_tag <= self._last_time_tag:
                return
            self._last_time_tag = t_tag

            # update gauges
            self._g_bz.set_value(row["Bz_GSM_nT"])
            self._g_bt.set_value(row["Mag_Field_Total_nT"])
            self._g_spd.set_value(row["Solar_Wind_Speed_kmps"])
            self._g_den.set_value(row["Proton_Density_per_cm3"])
            self._g_tmp.set_value(row["Plasma_Temperature_K"])
            self._lbl_updated.setText("Last update: " + t_tag.strftime("%H:%M:%S UTC"))

            # write CSV
            if self.recording and self._csv_path:
                out = row.copy()
                out["timestamp"] = datetime.utcnow().isoformat()
                df = pd.DataFrame([out])
                df.to_csv(self._csv_path, mode="a", header=not self._csv_path.exists(), index=False)
        finally:
            self._lock.release()

    # ------------------- NOAA helper -------------------------------
    @staticmethod
    def _latest_row() -> pd.Series | None:
        try:
            mag_raw = requests.get(_MAG_URL, timeout=10).json()
            mag_df = pd.DataFrame([mag_raw[-1]], columns=mag_raw[0]).rename(columns=_COL_RENAME_MAG)
            mag_df["time_tag"] = pd.to_datetime(mag_df["time_tag"])

            pl_raw = requests.get(_PLASMA_URL, timeout=10).json()
            pl_df = pd.DataFrame([pl_raw[-1]], columns=pl_raw[0]).rename(columns=_COL_RENAME_PLASMA)
            pl_df["time_tag"] = pd.to_datetime(pl_df["time_tag"])

            merged = pd.merge(mag_df, pl_df, on="time_tag", how="inner")
            if merged.empty:
                return None

            numeric_cols = [
                "Bx_GSM_nT",
                "By_GSM_nT",
                "Bz_GSM_nT",
                "Mag_Field_Total_nT",
                "Proton_Density_per_cm3",
                "Solar_Wind_Speed_kmps",
                "Plasma_Temperature_K",
            ]
            merged[numeric_cols] = merged[numeric_cols].apply(pd.to_numeric, errors="coerce")
            return merged.iloc[0]
        except Exception:
            return None  # swallow network / JSON errors silently
