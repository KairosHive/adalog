from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox
from PyQt6.QtCore import Qt
from adalog.base_modality import BaseModality
from oscpy.client import OSCClient
from oscpy.server import OSCThreadServer
from threading import Thread
from goofi.manager import Manager
from pathlib import Path
from pylsl import resolve_streams
import os
from threading import Timer


class Eeg(BaseModality):
    def __init__(self):
        super().__init__()
        self.recording = False
        self.session_dir = None

        # OSC communication setup
        self.osc_client = OSCClient("127.0.0.1", 5005)
        self.osc_server = OSCThreadServer()
        self.osc_server.listen("127.0.0.1", 5008, default=True)
        self.osc_server.bind(b"/eeg_quality", self.update_eeg_quality)

        # Launch Goofi patch in a thread
        self.gfi_thread = Thread(
            target=Manager,
            kwargs=dict(filepath=Path(__file__).parent / "eeg.gfi", headless=True),
            daemon=True,
        )
        self.gfi_thread.start()

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()

        self.quality_label = QLabel("EEG Quality: Unknown")
        self.quality_label.setStyleSheet("color:gray; font-weight:bold;")
        layout.addWidget(self.quality_label)

        row = QHBoxLayout()
        self.device_dropdown = QComboBox()
        self.device_dropdown.setFixedWidth(150)
        self.device_dropdown.currentTextChanged.connect(self.send_selected_stream)  # <- added

        row.addWidget(QLabel("Stream:"))
        row.addWidget(self.device_dropdown)

        self.refresh_btn = QPushButton("🔄 Refresh Streams")
        self.refresh_btn.clicked.connect(self.refresh_streams)
        row.addWidget(self.refresh_btn)

        layout.addLayout(row)
        self.setLayout(layout)

        self.refresh_streams()

    def send_selected_stream(self, stream_name):
        if stream_name and "No streams" not in stream_name:
            self.osc_client.send_message(b"/lsl_stream_selected", [stream_name.encode()])

    def refresh_streams(self):
        self.device_dropdown.clear()
        streams = resolve_streams()
        if not streams:
            self.device_dropdown.addItem("No streams available")
        else:
            for stream in streams:
                label = f"{stream.source_id()} ({stream.name()} @ {stream.hostname()})"
                self.device_dropdown.addItem(label)

    def start_recording(self, session_dir):
        self.session_dir = session_dir
        self.recording = True

        eeg_file_path = os.path.join(session_dir, "eeg.csv")
        self.osc_client.send_message(b"/recording_path", [eeg_file_path.encode()])

        selected_stream = self.device_dropdown.currentText()
        if selected_stream and "No streams" not in selected_stream:
            self.osc_client.send_message(b"/lsl_stream_selected", [selected_stream.encode()])

        # Schedule recording start after 50ms
        Timer(0.05, lambda: self.osc_client.send_message(b"/recording_start", [1.0])).start()

    def stop_recording(self):
        if not self.recording:
            return
        self.recording = False
        self.osc_client.send_message(b"/recording_stop", [1])

    def update_eeg_quality(self, quality):
        if isinstance(quality, (bytes, bytearray)):
            quality = float(quality.decode())

        if quality == 0:
            status, color = "Disconnected", "red"
        elif quality == 1:
            status, color = "Bad Signal", "orange"
        elif quality == 2:
            status, color = "Good Signal", "green"
        else:
            status, color = "Unknown", "gray"

        self.quality_label.setText(f"EEG Quality: {status}")
        self.quality_label.setStyleSheet(f"color:{color}; font-weight:bold;")

    def closeEvent(self, _):
        self.osc_server.terminate_server()
        self.osc_server.join_server()
