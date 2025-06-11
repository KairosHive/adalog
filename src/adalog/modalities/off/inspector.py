# adalog/modalities/off/inspector.py
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Set, Tuple
import time
import pandas as pd
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,    
)
from PyQt6.QtWidgets import QComboBox
from PyQt6.QtGui import QAction
from PyQt6.QtCore import QTimer
from matplotlib.ticker import FuncFormatter
# ➊  OFF-runtime base class (tiny)
# ────────────────────────────────────────────────────────────
from adalog.base_modality import BaseModalityOff

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
import matplotlib.pyplot as plt
import numpy as np


# ➋  Small helpers
# ────────────────────────────────────────────────────────────
SF_EEG = 256
PANEL_COLORS = {
    "Text": "#8ad38a",
    "Eeg": "#b157d1",
    "Drawing": "#7a6ed2",
    "Meteo": "#d45d5d",
    "Audio": "#5579d4",
    "Osc": "#d4a557",  # Added Osc modality color
}
MOD_LIST = ["Text", "Eeg", "Drawing", "Meteo", "Audio", "Osc"]  # Added Osc


def human_duration(seconds: float, long: bool = True) -> str:
    """Format duration in seconds to human-readable string."""
    if seconds < 1:
        return f"{seconds:.2f}s"
    
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    
    result = ""
    if h:
        if long:
            result = f"{h}h {m:02d}m {s:02d}s"
        else:
            result = f"{h}h {m:02d}m"
    elif m:
        result = f"{m}m {s:02d}s"
    else:
        result = f"{s}s"
    if long:
        return result
    return result.replace(" ", "")


class CheckableCombo(QLineEdit):
    """Minimal multi-select combo (click to open menu)."""
    changed = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setReadOnly(True)
        self._all: List[str] = []
        self._checked: Set[str] = set()
        self.setPlaceholderText("<all>")

    # public API --------------------------------------------------
    def clear(self) -> None:
        self._all.clear()
        self._checked.clear()
        self.setText("")

    def add_item(self, txt: str) -> None:
        self._all.append(txt)

    def checked(self) -> List[str]:
        return sorted(self._checked)

    # simple popup menu ------------------------------------------
    def mousePressEvent(self, ev):
        import PyQt6.QtWidgets as QW

        from PyQt6.QtWidgets import QMenu

        menu = QMenu(self)
        for t in self._all:
            act = QAction(t, menu)  # <-- FIXED: QAction from QtGui
            act.setCheckable(True)
            act.setChecked(t in self._checked)
            act.toggled.connect(
                lambda state, tag=t: (
                    self._checked.add(tag) if state else self._checked.discard(tag)
                )
            )
            menu.addAction(act)

        if self._all:
            menu.addSeparator()
            clear = menu.addAction("✓ everything / clear")
            clear.triggered.connect(lambda: self._checked.clear())

        menu.exec(ev.globalPosition().toPoint())

        self.setText(", ".join(self._checked) or "<all>")
        self.changed.emit()

class OverlapMatrixCanvas(FigureCanvas):
    def __init__(self, sel, overlaps, mod_durations):
        fig, ax = plt.subplots(figsize=(3, 3), dpi=200, facecolor='none')
        super().__init__(fig)

        #self.setFixedWidth(280)  # 👈 Prevents canvas from stretching too wide
        self.setStyleSheet("background: transparent; border: 0px; margin: 0px; padding: 0px;")
        self.setContentsMargins(0, 0, 0, 0)

        n = len(sel)
        matrix = np.zeros((n, n))
        for i, a in enumerate(sel):
            for j, b in enumerate(sel):
                if i != j:
                    dur = overlaps.get((a, b), overlaps.get((b, a), 0.0))
                    matrix[i, j] = dur

        # add diagonal with modality durations
        for i, m in enumerate(sel):
            matrix[i, i] = mod_durations.get(m, 0.0)
        
        # Mask upper triangle and zero values to make them transparent
        mask = np.triu(np.ones_like(matrix, dtype=bool), k=1) | (matrix == 0)
        matrix_masked = np.ma.masked_where(mask, matrix)
        
        # Display matrix as heatmap
        cax = ax.matshow(matrix_masked, cmap='viridis', alpha=0.8)
        
        # Custom formatter: show seconds only if <10min
        def short_human_duration(val):
            if val < 600:
                return human_duration(val, long=False)
            else:
                # Show only h and m, no seconds
                s = int(val)
                h, rem = divmod(s, 3600)
                m, _ = divmod(rem, 60)
                if h:
                    return f"{h}h{m:02d}"
                else:
                    return f"{m}m"
        
        cbar = fig.colorbar(cax, ax=ax, shrink=0.7)
        cbar.ax.yaxis.set_major_formatter(FuncFormatter(lambda x, pos: short_human_duration(x)))

        # Make colorbar text white
        cbar.ax.yaxis.set_tick_params(color='white')
        plt.setp(cbar.ax.yaxis.get_ticklabels(), color='white', fontsize=10)

        ax.set_xticks(range(n))
        ax.set_yticks(range(n))
        ax.set_xticklabels(sel, rotation=90, ha='left', fontsize=9, color='white')
        ax.set_yticklabels(sel, fontsize=9, color='white')
        ax.xaxis.set_ticks_position('bottom')
        ax.tick_params(colors='white')
        ax.set_title("Bimodal Data Length", pad=10, fontsize=10, color='white')

        for (i, j), val in np.ndenumerate(matrix):
            # Only show text for diagonal and lower triangle and if value is larger than 0
            if val > 0 and j <= i:
                ax.text(j, i, short_human_duration(val), ha='center', va='center', fontsize=7, color='white')

        ax.set_aspect('equal')
        ax.grid(False)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['bottom'].set_visible(False)
        ax.spines['left'].set_visible(False)
        fig.patch.set_alpha(0.0)
        ax.set_facecolor('none')
        fig.tight_layout()




# ➌  StatsPanel (same logic as in adalog_off, copied verbatim)
# ────────────────────────────────────────────────────────────
class StatsPanel(QWidget):
    """Left column: per-modality stats — Right: overlap-time matrix."""

    def __init__(self, root: Path):
        super().__init__()
        self.root = root
        self.user: str | None = None
        self.tags: Set[str] = set()
        self.mods: Set[str] = set()

        # Overall layout
        hbox = QHBoxLayout(self)
        hbox.setSpacing(10)  # Reduce spacing between stats and matrix
        hbox.setContentsMargins(0, 0, 0, 0)
        self.setContentsMargins(0, 0, 0, 0)

        # Stats grid
        self.stats_grid = QGridLayout()
        self.stats_grid.setHorizontalSpacing(12)
        self.stats_grid.setVerticalSpacing(6)

        # Matrix grid (right side)
        self.mat_grid = QGridLayout()
        self.mat_grid.setContentsMargins(0, 0, 0, 0)
        self.mat_grid.setHorizontalSpacing(0)
        self.mat_grid.setVerticalSpacing(0)

        # Assemble layout
        hbox.addLayout(self.stats_grid)
        hbox.addSpacing(10)  # Controlled, minimal spacing
        # Matrix container to control its size and alignment
        matrix_wrapper = QVBoxLayout()
        matrix_wrapper.setContentsMargins(0, 0, 0, 0)
        matrix_wrapper.setSpacing(0)
        matrix_wrapper.addLayout(self.mat_grid)
        matrix_wrapper.addStretch()  # Optional: to align matrix to top

        hbox.addLayout(matrix_wrapper)



    # public -----------------------------------------------------
    def set_filters(self, user: str, tags: List[str], mods: List[str]) -> None:
        self.user = user or None
        self.tags = set(tags)
        self.mods = set(mods)
        self._refresh()

    # internal ---------------------------------------------------
    def _refresh(self):
        if not self.user:
            return
        stats, overlaps = self._collect()
        self._populate(stats, overlaps)

    def _collect(self) -> Tuple[Dict[str, object], Dict[Tuple[str, str], float]]:
        p_user = self.root / self.user
        sessions = [d for d in p_user.glob("*") if d.is_dir()]

        # tag filtering
        def tag_ok(sess: Path) -> bool:
            if not self.tags:
                return True
            tc = sess / "tags.csv"
            if not tc.exists():
                return False
            try:
                df = pd.read_csv(tc)
                return self.tags.issubset(
                    set(sum(df["tags"].str.split(", ").tolist(), []))
                )
            except Exception:
                return False

        sessions = [s for s in sessions if tag_ok(s)]

        data = {m: {"sessions": 0, "dur": 0.0, "words": 0, "pngs": 0} for m in MOD_LIST}
        overlaps: Dict[Tuple[str, str], float] = {
            (a, b): 0.0 for a in MOD_LIST for b in MOD_LIST if a < b
        }

        # helper for CSV span
        def span(csv: Path, col="timestamp", fmt=None) -> float:
            try:
                df = pd.read_csv(csv, usecols=[col])
                if df.empty:
                    return 0.0
                ts = pd.to_datetime(df[col], format=fmt, errors="coerce").dropna()
                return 0.0 if ts.empty else (ts.iloc[-1] - ts.iloc[0]).total_seconds()
            except Exception:
                return 0.0

        # iterate sessions
        for sess in sessions:
            present_dur: Dict[str, float] = {}
            present = set()

            # TEXT --------------------------------------------------
            if not self.mods or "Text" in self.mods:
                txt_dir = sess / "Text"
                csv, tf = txt_dir / "text.csv", txt_dir / "text_final.txt"
                words, dur = 0, 0.0
                if csv.exists():
                    try:
                        df = pd.read_csv(csv)
                        words = len(df)
                        dur = span(csv)
                    except Exception:
                        pass
                elif tf.exists():
                    try:
                        words = len(tf.read_text(encoding="utf-8").split())
                    except Exception:
                        pass
                if words or dur:
                    present.add("Text")
                    data["Text"]["sessions"] += 1
                    data["Text"]["words"] += words
                    data["Text"]["dur"] += dur
                    present_dur["Text"] = dur

            # EEG ---------------------------------------------------
            if not self.mods or "Eeg" in self.mods:
                eeg_dir = sess / "Eeg"
                csvs = list(eeg_dir.glob("*.csv"))
                if csvs:
                    try:
                        n_rows = sum(1 for _ in open(csvs[0], encoding="utf-8")) - 1
                        if n_rows > 0:
                            dur = n_rows / SF_EEG
                            present.add("Eeg")
                            data["Eeg"]["sessions"] += 1
                            data["Eeg"]["dur"] += dur
                            present_dur["Eeg"] = dur
                    except Exception:
                        pass

            # DRAWING ----------------------------------------------
            if not self.mods or "Drawing" in self.mods:
                ddir = sess / "Drawing"
                pngs = list(ddir.rglob("*.png"))
                csv_draw = ddir / "drawings.csv"
                dur = span(csv_draw, fmt="%Y-%m-%dT%H-%M-%S-%f")
                if pngs or dur:
                    present.add("Drawing")
                    data["Drawing"]["sessions"] += 1
                    data["Drawing"]["pngs"] += len(pngs)
                    data["Drawing"]["dur"] += dur
                    present_dur["Drawing"] = dur
            # METEO -----------------------------------------------
            if not self.mods or "Meteo" in self.mods:
                meteo_dir = sess / "Meteo"
                csv = meteo_dir / "meteo.csv"
                dur = span(csv)
                if dur > 0:
                    present.add("Meteo")
                    data["Meteo"]["sessions"] += 1
                    data["Meteo"]["dur"] += dur
                    present_dur["Meteo"] = dur
            # AUDIO -----------------------------------------------
            if not self.mods or "Audio" in self.mods:
                audio_dir = sess / "Audio"
                wav_files = list(audio_dir.glob("*.wav"))
                # load first wav file to get duration
                dur = 0.0
                if wav_files:
                    try:
                        import soundfile as sf
                        with sf.SoundFile(wav_files[0]) as f:
                            dur = len(f) / f.samplerate
                    except Exception:
                        pass
                if dur > 0:
                    present.add("Audio")
                    data["Audio"]["sessions"] += 1
                    data["Audio"]["dur"] += dur
                    present_dur["Audio"] = dur
            # Osc ---------------------------------------------------
            if not self.mods or "Osc" in self.mods:
                osc_dir = sess / "Osc"
                csv = osc_dir / "osc.csv"
                msgs, dur = 0, 0.0
                if csv.exists():
                    try:
                        df = pd.read_csv(csv)
                        msgs = len(df)
                        dur = span(csv)
                    except Exception:
                        pass
                if msgs or dur:
                    present.add("Osc")
                    data["Osc"]["sessions"] += 1
                    data["Osc"]["words"] += msgs  # treat messages as "words"
                    data["Osc"]["dur"] += dur
                    present_dur["Osc"] = dur
            # overlaps ---------------------------------------------
            for a in present:
                for b in present:
                    if a < b:
                        overlaps[(a, b)] += min(
                            present_dur.get(a, 0.0), present_dur.get(b, 0.0)
                        )

        return data, overlaps

    def _populate(
        self, st: Dict[str, object], overlaps: Dict[Tuple[str, str], float]
    ) -> None:
        # clear old widgets
        for grid in (self.stats_grid, self.mat_grid):
            while grid.count():
                w = grid.takeAt(0).widget()
                if w:
                    w.deleteLater()

        # stats (left column) ------------------------------------
        row = 0
        for mod in MOD_LIST:
            info = st[mod]
            if info["sessions"] == 0:
                continue
            col = PANEL_COLORS[mod]
            hdr = QLabel(f"{mod} stats")
            hdr.setStyleSheet(f"color:{col}; font-size:18px; font-weight:bold;")
            self.stats_grid.addWidget(hdr, row, 0, 1, 2)
            row += 1

            def add(label, value):
                self.stats_grid.addWidget(QLabel(label), row, 0)
                self.stats_grid.addWidget(QLabel(value), row, 1)

            add("Sessions:", str(info["sessions"])); row += 1
            if mod == "Text" or mod == "Osc":
                add("Total messages:" if mod == "Osc" else "Total words:", f"{info['words']:,}"); row += 1
                avg = info["words"] / info["sessions"] if info["sessions"] else 0
                add("Avg/messages per session:" if mod == "Osc" else "Avg words/session:", f"{avg:.1f}"); row += 1
                if info["dur"]:
                    add("Total time:", human_duration(info["dur"])); row += 1
            elif mod == "Eeg":
                add("Total time:", human_duration(info["dur"])); row += 1
                avg = info["dur"] / info["sessions"] if info["sessions"] else 0
                add("Avg/session:", human_duration(avg)); row += 1
            elif mod == "Drawing":
                add("PNGs:", str(info["pngs"])); row += 1
                add("Total time:", human_duration(info["dur"])); row += 1
            elif mod == "Meteo":
                add("Total time:", human_duration(info["dur"])); row += 1
            elif mod == "Audio":
                add("Total time:", human_duration(info["dur"])); row += 1
            row += 1  # blank line

        self.stats_grid.setRowStretch(row, 1)

        # ────── Overlap matrix (right column) ──────
        sel = [m for m in MOD_LIST if (not self.mods or m in self.mods) and st[m]["sessions"]]
        if len(sel) < 2:
            return

        # Title — tightened margin below
        title = QLabel("Overlap matrix")
        title.setStyleSheet("font-weight: bold; font-size: 13px; margin: 0px 0px 2px 0px;")
        # Clear existing layout
        while self.mat_grid.count():
            w = self.mat_grid.takeAt(0).widget()
            if w:
                w.setParent(None)
        mod_durations = {m: st[m]["dur"] for m in sel}
        canvas = OverlapMatrixCanvas(sel, overlaps, mod_durations)
        self.mat_grid.addWidget(canvas, 0, 0)


# ────────────────────────────────────────────────────────────
# ➍  Inspector (dockable) — what the host app loads
# ────────────────────────────────────────────────────────────
class Inspector(BaseModalityOff):
    """Dataset inspector dock (tags, modality filters, overlap matrix)."""

    def __init__(self):
        super().__init__()
        
        # sessions root is provided by the host MainWindow
        root = Path(getattr(self.window(), "sessions_root", "sessions"))
        self.stats = StatsPanel(root)
        self.loaded_user = None

        # compact filter bar ------------------------------------
        self.user_combo = QComboBox()
        self.user_combo.setEditable(True)
        self.user_combo.setPlaceholderText("user…")
        self.user_combo.lineEdit().returnPressed.connect(self._load_user)
        self.user_combo.currentTextChanged.connect(self._on_user_text_changed)
        self.user_combo.setMinimumContentsLength(20)
        self._last_user_edit = time.time()
        self.delay_user_edit = QTimer()
        self.delay_user_edit.setInterval(20)  # 20ms debounce
        self.delay_user_edit.setSingleShot(True)
        self.delay_user_edit.timeout.connect(self._load_user)
        self.debounce_user_edit = QTimer()
        self.debounce_user_edit.setInterval(1000)  # 1s debounce
        self.debounce_user_edit.setSingleShot(True)
        self.debounce_user_edit.timeout.connect(self._load_user)
        
        # Populate with discovered users
        self._populate_users()

        self.tags_cb = CheckableCombo(); self.tags_cb.changed.connect(self._refresh)
        self.mods_cb = CheckableCombo(); self.mods_cb.changed.connect(self._refresh)

        bar = QHBoxLayout(); bar.setSpacing(6); bar.setContentsMargins(0, 0, 0, 0)
        for w in (
            QLabel("👤"), self.user_combo,
            QLabel("Tags:"), self.tags_cb,
            QLabel("Modalities:"), self.mods_cb
        ):
            bar.addWidget(w)
        bar.addStretch()

        top = QWidget(); top.setLayout(bar)

        # stats in a scroller -----------------------------------
        scr = QScrollArea(); scr.setWidgetResizable(True); scr.setWidget(self.stats)

        lay = QVBoxLayout(self); lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(top); lay.addWidget(scr, 1)
        self.setMinimumWidth(300)

    # ----------------------------------------------------------
    def _populate_users(self):
        """Discover and populate user dropdown with existing users."""
        try:
            users = []
            for user_dir in self.stats.root.glob("*"):
                if user_dir.is_dir() and not user_dir.name.startswith("."):
                    users.append(user_dir.name)
            
            self.user_combo.addItems(sorted(users))
        except Exception:
            pass  # If root doesn't exist or other error, just continue

    def _on_user_text_changed(self):
        """Handle user text changes with debouncing to avoid excessive API calls."""
        # Calculate time since last edit
        delta_ms = (time.time() - self._last_user_edit) * 1000
        self._last_user_edit = time.time()

        # If user hasn't actually changed, stop all timers
        if self.loaded_user == self.user_combo.currentText().strip():
            self.delay_user_edit.stop()
            self.debounce_user_edit.stop()
            return

        # If enough time has passed or delay timer is already active, use short delay
        if delta_ms > self.debounce_user_edit.interval() or self.delay_user_edit.isActive():
            self.delay_user_edit.stop()
            self.delay_user_edit.start()
        # If user is still typing rapidly, use longer debounce
        elif delta_ms < self.debounce_user_edit.interval():
            self.debounce_user_edit.stop()
            self.debounce_user_edit.start()

    def _load_user(self):
        user = self.user_combo.currentText().strip()
        if not user:
            return
        self.tags_cb.clear(); self.mods_cb.clear()

        p = self.stats.root / user
        tags, mods = set(), set()
        for sess in p.glob("*"):
            tc = sess / "tags.csv"
            if tc.exists():
                try:
                    df = pd.read_csv(tc)
                    tags.update(sum(df["tags"].str.split(", ").tolist(), []))
                except Exception:
                    pass
            for sub in sess.iterdir():
                if sub.is_dir():
                    mods.add(sub.name)

        for t in sorted(tags): self.tags_cb.add_item(t)
        for m in sorted(mods): self.mods_cb.add_item(m)
        self._refresh()

    def _refresh(self):
        self.loaded_user = self.user_combo.currentText().strip()
        self.stats.set_filters(
            self.loaded_user,
            self.tags_cb.checked(),
            self.mods_cb.checked(),
        )
