import os
import queue
import threading
import time
from datetime import datetime
from threading import Thread

import numpy as np
import sounddevice as sd
import soundfile as sf
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout

from adalog.base_modality import BaseModalityRec


class Audio(BaseModalityRec):
    """
    Live level meter (always) + file writer (only while a session is running).
    The meter is refreshed by a QTimer (30 FPS) to avoid Qt-queue flooding.
    """

    def __init__(self):
        super().__init__()

        # ---------------- runtime state --------------------------------------
        self.session_dir = None
        self.recording = False
        self._queue = queue.Queue()  # audio → writer thread
        self._writer = None
        self._writer_thread = None
        self._stream = None

        # most-recent RMS (0-1), guarded by a lock for thread safety
        self._latest_rms = 0.0
        self._rms_lock = threading.Lock()

        # ---------------- GUI -------------------------------------------------
        self._build_ui()

        # start monitoring right away
        self._open_monitor_stream()

        # timer to refresh the progress-bar
        self._meter_timer = QTimer(self)
        self._meter_timer.setInterval(33)  # ~30 Hz
        self._meter_timer.timeout.connect(self._update_level_bar)
        self._meter_timer.start()

    # ────────────────────────── UI ──────────────────────────────────────────
    def _build_ui(self):
        layout = QVBoxLayout()

        row = QHBoxLayout()
        row.addWidget(QLabel("Input device:"))
        self.device_box = QComboBox()
        self.device_box.setMaximumWidth(300)
        for idx, dev in enumerate(sd.query_devices()):
            if dev["max_input_channels"] > 0:
                self.device_box.addItem(f"{idx}: {dev['name']}", userData=idx)
        self.device_box.currentTextChanged.connect(self._on_device_changed)
        row.addWidget(self.device_box)
        row.addStretch()
        layout.addLayout(row)

        self._level_bar = QProgressBar()
        self._level_bar.setRange(0, 100)
        self._level_bar.setMaximumHeight(40)
        self._level_bar.setMaximumWidth(400)
        self._level_bar.setTextVisible(False)
        layout.addWidget(self._level_bar)

        self.setLayout(layout)

    # ───────────────────── stream management ────────────────────────────────
    def _open_monitor_stream(self):
        """Start/Restart an InputStream that feeds the level meter."""
        if self._stream:
            self._stream.stop()
            self._stream.close()

        idx = self.device_box.currentData()
        self._stream = sd.InputStream(
            samplerate=48_000,
            channels=1,
            blocksize=1024,
            dtype="float32",
            device=idx,
            callback=self._audio_callback,
        )
        self._stream.start()

    def _on_device_changed(self, _text: str):
        self._open_monitor_stream()

    # ─────────────────── session control (called by MainWindow) ─────────────
    def start_recording(self, session_dir: str):
        if self.recording:
            return

        # file path with UTC start timestamp
        tstamp = datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%S-%fZ")
        wav_path = os.path.join(session_dir, f"audio_{tstamp}.wav")

        # purge any stale data
        with self._queue.mutex:
            self._queue.queue.clear()

        self._writer = sf.SoundFile(wav_path, mode="w", samplerate=48_000, channels=1, subtype="PCM_16")
        self._writer_thread = Thread(target=self._drain_queue_to_file, daemon=True)
        self._writer_thread.start()

        self.session_dir = session_dir
        self.recording = True

    def stop_recording(self):
        if not self.recording:
            return
        self.recording = False

        self._queue.put(None)  # sentinel to end writer thread
        self._writer_thread.join()
        self._writer.close()
        self._writer = None

    # ───────────────────────── audio callbacks ──────────────────────────────
    def _audio_callback(self, indata, frames, time_info, status):
        # store RMS for the meter
        rms = np.sqrt(np.mean(indata**2))
        with self._rms_lock:
            self._latest_rms = rms

        # enqueue audio for file writer only when recording
        if self.recording:
            self._queue.put(indata.copy())

    def _drain_queue_to_file(self):
        while True:
            chunk = self._queue.get()
            if chunk is None:  # sentinel
                break
            self._writer.write(chunk)

    # ───────────────────────── GUI update (timer) ───────────────────────────
    def _update_level_bar(self):
        with self._rms_lock:
            value = int(min(self._latest_rms, 1.0) * 100)
        self._level_bar.setValue(value)

    # ───────────────────────── housekeeping ────────────────────────────────
    def closeEvent(self, _event):
        self.stop_recording()
        if self._stream:
            self._stream.stop()
            self._stream.close()
        self.stop_recording()
        if self._stream:
            self._stream.stop()
            self._stream.close()
