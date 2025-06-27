import os
from datetime import datetime
from pathlib import Path
from threading import Thread

import numpy as np
import sounddevice as sd
import soundfile as sf
from goofi.manager import Manager
from oscpy.client import OSCClient
from oscpy.server import OSCThreadServer
from pylsl import resolve_streams
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from adalog.base_modality import BaseModalityOn
from adalog.utils import get_asset_path


class DreamIncubator(BaseModalityOn):
    def __init__(self):
        super().__init__()
        self.goofi_thread = None
        self.goofi_manager = None
        self.osc_server = OSCThreadServer()
        self.osc_server.listen("127.0.0.1", 5009, default=True)
        self.osc_server.bind(b"/alpha_theta_ratio", self.update_alpha_theta_ratio)
        self.osc_server.bind(b"/lziv_complexity", self.update_lziv_complexity)
        self.osc_server.bind(b"/duration", self.update_duration)  # New OSC binding for duration
        self.osc_client = OSCClient("127.0.0.1", 5010)  # OSC client to send messages to Goofi

        self.is_recording_audio = False
        self.audio_frames = []
        self.audio_samplerate = 44100  # Default sample rate
        self.audio_channels = 1  # Default channels
        self.audio_stream = None
        self.recorded_audio_path = None

        # Start Goofi patch immediately in a separate thread
        patch_path = Path(__file__).parent / "dream_incubator.gfi"
        if not patch_path.exists():
            print(f"Error: Goofi patch not found at {patch_path}")
        else:
            self.goofi_thread = Thread(
                target=Manager,
                kwargs=dict(filepath=patch_path, headless=True),
                daemon=True,
            )
            # self.goofi_thread.start()
            print(f"Started Goofi with patch: {patch_path}")

        self.setup_ui()
        self.refresh_streams()  # Initial refresh

    def setup_ui(self):
        layout = QVBoxLayout()

        self.start_button = QPushButton("Start Dream Incubation")
        self.start_button.clicked.connect(self.start_dream_incubation)
        layout.addWidget(self.start_button)

        self.reset_button = QPushButton("Reset Dream Incubation")
        self.reset_button.clicked.connect(self.reset_dream_incubation)
        self.reset_button.setEnabled(False)  # Disable until started
        layout.addWidget(self.reset_button)

        self.alpha_theta_label = QLabel("Alpha/Theta Ratio: N/A")
        layout.addWidget(self.alpha_theta_label)

        self.lziv_complexity_label = QLabel("LZiv Complexity: N/A")
        layout.addWidget(self.lziv_complexity_label)

        self.duration_label = QLabel("Duration: 00:00")
        layout.addWidget(self.duration_label)

        # Audio File Selection and Recording
        audio_layout = QHBoxLayout()
        self.select_audio_btn = QPushButton("Select Audio File")
        self.select_audio_btn.clicked.connect(self.select_audio_file)
        audio_layout.addWidget(self.select_audio_btn)

        self.record_audio_btn = QPushButton("Start Recording")
        self.record_audio_btn.clicked.connect(self.toggle_audio_recording)
        audio_layout.addWidget(self.record_audio_btn)

        layout.addLayout(audio_layout)

        self.current_audio_label = QLabel("Current Audio: None")
        layout.addWidget(self.current_audio_label)

        # LSL Stream Selector
        row = QHBoxLayout()
        self.device_dropdown = QComboBox()
        self.device_dropdown.setFixedWidth(150)
        self.device_dropdown.currentTextChanged.connect(self.send_selected_stream)

        row.addWidget(QLabel("Stream:"))
        row.addWidget(self.device_dropdown)
        layout.addLayout(row)

        self.refresh_btn = QPushButton("🔄 Refresh Streams")
        self.refresh_btn.clicked.connect(self.refresh_streams)
        layout.addWidget(self.refresh_btn)

        layout.addStretch(1)
        self.setLayout(layout)

        self.refresh_streams()  # Initial refresh

    def start_dream_incubation(self):
        self.osc_client.send_message(b"/start_incubation", [1])
        self.start_button.setEnabled(False)
        self.reset_button.setEnabled(True)
        self.alpha_theta_label.setText("Alpha/Theta Ratio: Running...")
        self.lziv_complexity_label.setText("LZiv Complexity: Running...")
        self.duration_label.setText("Duration: Running...")
        print("Sent OSC message to start incubation.")

    def reset_dream_incubation(self):
        self.osc_client.send_message(b"/reset_incubation", [1])
        self.start_button.setEnabled(True)
        self.reset_button.setEnabled(False)
        self.alpha_theta_label.setText("Alpha/Theta Ratio: N/A")
        self.lziv_complexity_label.setText("LZiv Complexity: N/A")
        self.duration_label.setText("Duration: 00:00")
        print("Sent OSC message to reset incubation.")

    def update_alpha_theta_ratio(self, value):
        if isinstance(value, (bytes, bytearray)):
            value = float(value.decode())
        self.alpha_theta_label.setText(f"Alpha/Theta Ratio: {value:.2f}")

    def update_lziv_complexity(self, value):
        if isinstance(value, (bytes, bytearray)):
            value = float(value.decode())
        self.lziv_complexity_label.setText(f"LZiv Complexity: {value:.2f}")

    def update_duration(self, value):
        if isinstance(value, (bytes, bytearray)):
            value = float(value.decode())
        minutes, seconds = divmod(int(value), 60)
        self.duration_label.setText(f"Duration: {minutes:02d}:{seconds:02d}")

    def select_audio_file(self):
        file_dialog = QFileDialog()
        file_path, _ = file_dialog.getOpenFileName(self, "Select Audio File", "", "Audio Files (*.wav *.flac *.ogg)")
        if file_path:
            self.current_audio_label.setText(f"Current Audio: {Path(file_path).name}")
            self.send_audio_path_to_goofi(file_path)

    def toggle_audio_recording(self):
        if not self.is_recording_audio:
            self.audio_frames = []
            self.audio_stream = sd.InputStream(
                samplerate=self.audio_samplerate, channels=self.audio_channels, callback=self.audio_callback
            )
            self.audio_stream.start()
            self.is_recording_audio = True
            self.record_audio_btn.setText("Stop Recording")
            self.current_audio_label.setText("Current Audio: Recording...")
        else:
            self.audio_stream.stop()
            self.audio_stream.close()
            self.is_recording_audio = False
            self.record_audio_btn.setText("Start Recording")

            # Save the recorded audio
            output_dir = Path.home() / ".adalog_audio_recordings"
            output_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_name = f"recorded_audio_{timestamp}.wav"
            self.recorded_audio_path = str(output_dir / file_name)
            sf.write(self.recorded_audio_path, np.concatenate(self.audio_frames), self.audio_samplerate)
            self.current_audio_label.setText(f"Current Audio: {file_name}")
            self.send_audio_path_to_goofi(self.recorded_audio_path)

    def audio_callback(self, indata, frames, time, status):
        self.audio_frames.append(indata.copy())

    def send_audio_path_to_goofi(self, audio_path):
        self.osc_client.send_message(b"/audio_file_path", [audio_path.encode()])

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
                label = f"{stream.source_id()}"
                self.device_dropdown.addItem(label)

    def start(self):
        # This method is called when the main system starts
        # We can potentially auto-start the dream incubation here or just leave it to the user button
        print("DreamIncubator panel received start signal from main system.")

    def stop(self):
        # This method is called when the main system stops
        self.reset_dream_incubation()
        print("DreamIncubator panel received stop signal from main system.")

    def closeEvent(self, event):
        self.osc_server.terminate_server()
        self.osc_server.join_server()
        if self.is_recording_audio and self.audio_stream:
            self.audio_stream.stop()
            self.audio_stream.close()
        if self.goofi_manager:
            self.goofi_manager.stop()
        if self.goofi_thread and self.goofi_thread.is_alive():
            self.goofi_thread.join(timeout=1)
        super().closeEvent(event)
        print("DreamIncubator panel received stop signal from main system.")

    def closeEvent(self, event):
        self.osc_server.terminate_server()
        self.osc_server.join_server()
        if self.goofi_manager:
            self.goofi_manager.stop()
        if self.goofi_thread and self.goofi_thread.is_alive():
            self.goofi_thread.join(timeout=1)
        super().closeEvent(event)
