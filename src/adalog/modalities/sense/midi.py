import os
import time
from datetime import datetime, timezone

import mido
from mido import MetaMessage, MidiFile, MidiTrack, bpm2tempo, second2tick
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from adalog.base_modality import BaseModalitySense

# ---------------------------------------------------------------------------
#  MIDI messages that cannot be stored in a Standard MIDI File (SMF v0/1)
#  and must therefore be removed before saving.
# ---------------------------------------------------------------------------
REALTIME_TYPES = {"clock", "start", "continue", "stop", "active_sensing", "reset", "timecode"}


class Midi(BaseModalitySense):
    """Adalog panel that records incoming MIDI data to a *.mid* file."""

    # emitted when a new event is captured so the GUI can update safely
    _events_changed = pyqtSignal(int)

    # ──────────────────────────────── init ────────────────────────────────
    def __init__(self):
        super().__init__()

        # internal state ----------------------------------------------------
        self.session_dir: str | None = None
        self.recording: bool = False
        self._port = None  # mido input port (opened on start)
        self._events: list[tuple[float, mido.Message]] = []
        self._start_time: float = 0.0
        self._midi_path: str | None = None

        # build UI & connect signals ---------------------------------------
        self._build_ui()
        self._events_changed.connect(lambda n: self._count_lbl.setText(f"Events: {n}"))

    # ────────────────────────────── UI helpers ────────────────────────────
    def _build_ui(self):
        layout = QVBoxLayout()

        # top row: device selector + refresh button
        row = QHBoxLayout()
        row.addWidget(QLabel("MIDI input:"))
        self.device_box = QComboBox()
        self._populate_devices()
        row.addWidget(self.device_box)
        refresh_btn = QPushButton("🔄")
        refresh_btn.setFixedWidth(30)
        refresh_btn.clicked.connect(self._populate_devices)
        row.addWidget(refresh_btn)
        row.addStretch()
        layout.addLayout(row)

        # live counter
        self._count_lbl = QLabel("Events: 0")
        layout.addWidget(self._count_lbl)

        self.setLayout(layout)

    def _populate_devices(self):
        """Refresh the drop‑down with currently available MIDI input ports."""
        self.device_box.blockSignals(True)
        self.device_box.clear()
        for name in mido.get_input_names():
            self.device_box.addItem(name)
        self.device_box.blockSignals(False)

    # ───────────────────── session control (MainWindow calls) ─────────────
    def start_recording(self, session_dir: str):
        if self.recording:
            return

        # create a file path with UTC timestamp
        tstamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%fZ")
        self._midi_path = os.path.join(session_dir, f"midi_{tstamp}.mid")

        # reset buffers / counters
        self._events.clear()
        self._events_changed.emit(0)

        # open the chosen MIDI input port (asynchronous callback mode)
        port_name = self.device_box.currentText()
        if not port_name:
            raise RuntimeError("No MIDI input device selected.")
        self._port = mido.open_input(port_name, callback=self._midi_callback)

        self.session_dir = session_dir
        self._start_time = time.time()
        self.recording = True

    def stop_recording(self):
        if not self.recording:
            return
        self.recording = False

        # close the port first (stops callbacks immediately)
        if self._port:
            self._port.close()
            self._port = None

        # ---------------- write SMF ---------------------------------------
        # Filter out real‑time messages that SMF cannot store.
        filtered = [(ts, msg) for ts, msg in self._events if msg.type not in REALTIME_TYPES]

        if not filtered:
            print("[Midi] No storable MIDI events captured; nothing written.")
            return

        tempo_us = bpm2tempo(120)  # assume 120‑BPM tempo grid
        mid = MidiFile(ticks_per_beat=480)  # PPQN resolution
        track = MidiTrack()
        mid.tracks.append(track)
        track.append(MetaMessage("set_tempo", tempo=tempo_us, time=0))

        prev_ts = 0.0
        for ts, msg in filtered:
            delta_sec = ts - prev_ts
            delta_tick = int(second2tick(delta_sec, mid.ticks_per_beat, tempo_us))
            track.append(msg.copy(time=delta_tick))
            prev_ts = ts

        mid.save(self._midi_path)
        print(f"[Midi] Saved {len(filtered)} events to {self._midi_path}")

    # ───────────────────── MIDI callback (background) ─────────────────────
    def _midi_callback(self, msg: mido.Message):
        """Called by the RtMidi backend thread for each incoming message."""
        if not self.recording:
            return
        elapsed = time.time() - self._start_time
        self._events.append((elapsed, msg))
        self._events_changed.emit(len(self._events))

    # ───────────────────────── housekeeping ───────────────────────────────
    def closeEvent(self, _event):
        # ensure graceful shutdown if panel is closed independently
        self.stop_recording()

    def closeEvent(self, _event):
        # ensure graceful shutdown if panel is closed independently
        self.stop_recording()
