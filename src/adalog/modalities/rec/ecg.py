from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QProgressBar
from PyQt6.QtCore import Qt, QTimer
from adalog.base_modality import BaseModalityRec
from oscpy.client import OSCClient
from oscpy.server import OSCThreadServer
from threading import Thread, Timer
from goofi.manager import Manager
from pathlib import Path
import os

class Ecg(BaseModalityRec):
    def __init__(self):
        super().__init__()
        self.recording = False
        self.session_dir = None

        # OSC communication setup (client for outgoing, server for incoming)
        self.osc_client = OSCClient("127.0.0.1", 9124)  # <-- pick a client port different from server!
        self.osc_server = OSCThreadServer()
        self.osc_server.listen("127.0.0.1", 9123, default=True)
        self.osc_server.bind(b"/ecg_raw", self.update_ecg_raw)
        self.osc_server.bind(b"/ecg_bpm", self.update_ecg_bpm)

        # Launch Goofi patch in a thread
        self.gfi_thread = Thread(
            target=Manager,
            kwargs=dict(filepath=Path(__file__).parent / "ecg.gfi", headless=True),
            daemon=True,
        )
        self.gfi_thread.start()

        self._latest_raw = 0.0
        self._build_ui()
        self._start_meter_timer()

    def _build_ui(self):
        layout = QVBoxLayout()

        # Raw signal display (like Audio's meter)
        raw_layout = QHBoxLayout()
        raw_layout.addWidget(QLabel("Raw Signal:"))
        self.raw_bar = QProgressBar()
        self.raw_bar.setRange(0, 100)
        self.raw_bar.setMaximumHeight(40)
        self.raw_bar.setMaximumWidth(400)
        self.raw_bar.setTextVisible(False)
        raw_layout.addWidget(self.raw_bar)
        layout.addLayout(raw_layout)

        # BPM display
        self.bpm_label = QLabel("BPM: --")
        self.bpm_label.setStyleSheet("font-weight:bold;")
        layout.addWidget(self.bpm_label, alignment=Qt.AlignmentFlag.AlignCenter)

        self.setLayout(layout)

    def _start_meter_timer(self):
        self._meter_timer = QTimer(self)
        self._meter_timer.setInterval(33)  # ~30Hz
        self._meter_timer.timeout.connect(self._update_level_bar)
        self._meter_timer.start()

    def _update_level_bar(self):
        value = int(min(self._latest_raw, 1.0) * 100)
        self.raw_bar.setValue(value)

    def start_recording(self, session_dir):
        self.session_dir = session_dir
        self.recording = True
        print(f"ECG recording started in {session_dir}")

        ecg_file_path = os.path.join(session_dir, "ecg.csv")
        self.osc_client.send_message(b"/recording_path", [ecg_file_path.encode()])

        # If you need stream selection logic, add here like EEG node

        # Schedule recording start after 50ms (like EEG)
        Timer(0.05, lambda: self.osc_client.send_message(b"/recording_start", [1.0])).start()

    def stop_recording(self):
        if not self.recording:
            return
        self.recording = False
        print("ECG recording stopped.")
        self.osc_client.send_message(b"/recording_stop", [1])

    def update_ecg_raw(self, value):
        if isinstance(value, (bytes, bytearray)):
            value = float(value.decode())
        self._latest_raw = float(value)

    def update_ecg_bpm(self, value):
        if isinstance(value, (bytes, bytearray)):
            value = float(value.decode())
        self.bpm_label.setText(f"BPM: {int(value)}")

    def closeEvent(self, _):
        self.osc_server.terminate_server()
        self.osc_server.join_server()
        self._meter_timer.stop()

if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication

    app = QApplication([])
    ecg = Ecg()
    ecg.show()
    app.exec()
