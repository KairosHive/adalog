import os
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from oscpy.server import OSCThreadServer
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
)

from adalog.base_modality import BaseModality


class Osc(BaseModality):
    """Adalog panel that records incoming OSC messages to a CSV file."""

    # Signal emitted when new OSC message arrives
    _message_received = pyqtSignal(str, object)

    def __init__(self):
        super().__init__()

        # Internal state
        self.session_dir = None
        self.recording = False
        self.server = None
        self.messages_lock = threading.Lock()
        self.recent_addresses = deque(maxlen=1000)  # Store recent addresses
        self.address_timestamps = defaultdict(float)  # Track last seen time per address

        # Build UI
        self._build_ui()

        # Connect signals
        self._message_received.connect(self._update_status_display)

        # Timer to update the address display (remove old addresses)
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self._update_address_display)
        self.update_timer.start(1000)  # Update every second

        # Start OSC server with default port
        self._start_osc_server()

    def _build_ui(self):
        layout = QVBoxLayout()

        # Port selection row
        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("OSC Port:"))
        self.port_spinbox = QSpinBox()
        self.port_spinbox.setRange(1024, 65535)
        self.port_spinbox.setValue(8000)
        self.port_spinbox.valueChanged.connect(self._on_port_changed)
        port_row.addWidget(self.port_spinbox)
        port_row.addStretch()
        layout.addLayout(port_row)

        # Store prefix setting row
        store_row = QHBoxLayout()
        store_row.addWidget(QLabel("Store Prefix:"))
        self.store_prefix_input = QLineEdit()
        self.store_prefix_input.setText("_store")
        self.store_prefix_input.setToolTip(
            "Messages sent to /<prefix>/filename will save their content to filename.txt in the session folder.\n"
            "Example: if prefix is '_store', sending a message to '/_store/myfile' will create myfile.txt"
        )
        store_row.addWidget(self.store_prefix_input)
        store_row.addStretch()
        layout.addLayout(store_row)

        # Status label
        self.status_label = QLabel("OSC Server: Starting...")
        self.status_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.status_label)

        # Message counter
        self.message_count_label = QLabel("Messages received: 0")
        layout.addWidget(self.message_count_label)

        # Recent addresses display
        layout.addWidget(QLabel("OSC addresses (last minute):"))
        self.address_display = QTextEdit()
        self.address_display.setReadOnly(True)
        layout.addWidget(self.address_display, 1)  # stretch factor 1 to take remaining space

        self.setLayout(layout)

    def _start_osc_server(self):
        """Start the OSC server on the specified port."""
        if self.server:
            self.server.stop_all()
            self.server.terminate_server()
            self.server.join_server()

        try:
            port = self.port_spinbox.value()
            self.server = OSCThreadServer(advanced_matching=True)
            self.server.listen(address="0.0.0.0", port=port, default=True)

            # Bind to possible addresses of depth 10 (same as goofi-pipe implementation)
            for i in range(1, 11):
                self.server.bind(b"/*" * i, self._osc_callback, get_address=True)

            self.status_label.setText(f"OSC Server: Listening on port {port}")
            self.status_label.setStyleSheet("color: green; font-weight: bold;")

        except Exception as e:
            self.status_label.setText(f"OSC Server: Error - {str(e)}")
            self.status_label.setStyleSheet("color: red; font-weight: bold;")

    def _on_port_changed(self, port):
        """Restart server when port changes."""
        self._start_osc_server()

    def _osc_callback(self, address, *args):
        """Called when an OSC message is received."""
        try:
            address_str = address.decode() if isinstance(address, bytes) else str(address)

            # Convert arguments to a suitable format
            if len(args) == 0:
                value = None
            elif len(args) == 1:
                arg = args[0]
                if isinstance(arg, bytes):
                    value = arg.decode()
                else:
                    value = arg
            else:
                # Multiple arguments - convert to list
                value = []
                for arg in args:
                    if isinstance(arg, bytes):
                        value.append(arg.decode())
                    else:
                        value.append(arg)

            # Check if this is a store message
            store_prefix = self.store_prefix_input.text().strip()
            if store_prefix and address_str.startswith(f"/{store_prefix}/"):
                self._handle_store_message(address_str, value, store_prefix)
                return  # Don't process as regular message

            # Update recent addresses tracking
            current_time = time.time()
            with self.messages_lock:
                self.recent_addresses.append((current_time, address_str))
                self.address_timestamps[address_str] = current_time

            # If recording, save to CSV
            if self.recording and self.session_dir:
                self._save_message(address_str, value)

            # Emit signal for UI update
            self._message_received.emit(address_str, value)

        except Exception as e:
            print(f"Error in OSC callback: {e}")

    def _handle_store_message(self, address, value, store_prefix):
        """Handle special store messages that save content to text files."""
        try:
            if not self.session_dir:
                print(f"Cannot store message: no session directory set")
                return

            # Extract filename from address (remove the /<prefix>/ part)
            prefix_part = f"/{store_prefix}/"
            if not address.startswith(prefix_part):
                return

            filename = address[len(prefix_part) :]
            if not filename:
                print(f"Store message has no filename: {address}")
                return

            # Sanitize filename to prevent directory traversal
            filename = filename.replace("/", "_").replace("\\", "_")
            if not filename.endswith(".txt"):
                filename += ".txt"

            # Convert value to string content
            if value is None:
                content = ""
            elif isinstance(value, list):
                content = "\n".join(str(item) for item in value)
            else:
                content = str(value)

            # Save to file
            file_path = os.path.join(self.session_dir, filename)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)

            print(f"Stored content to: {filename}")

        except Exception as e:
            print(f"Error handling store message: {e}")

    def _save_message(self, address, value):
        """Save OSC message to CSV file."""
        try:
            timestamp = datetime.now(timezone.utc).isoformat()
            csv_path = os.path.join(self.session_dir, "osc.csv")

            # Convert value to string representation
            if value is None:
                value_str = ""
            elif isinstance(value, list):
                value_str = str(value)
            else:
                value_str = str(value)

            # Create DataFrame and append to CSV
            df = pd.DataFrame([[timestamp, address, value_str]], columns=["timestamp", "address", "value"])
            df.to_csv(csv_path, mode="a", header=not os.path.exists(csv_path), index=False)

        except Exception as e:
            print(f"Error saving OSC message: {e}")

    def _update_status_display(self, address, value):
        """Update the message counter when a new message arrives."""
        current_count = int(self.message_count_label.text().split(": ")[1])
        self.message_count_label.setText(f"Messages received: {current_count + 1}")

    def _update_address_display(self):
        """Update the display of recent OSC addresses (remove old ones)."""
        current_time = time.time()
        cutoff_time = current_time - 60.0  # 1 minute ago

        with self.messages_lock:
            # Remove old addresses
            recent_in_minute = {}
            for addr, last_seen in self.address_timestamps.items():
                if last_seen >= cutoff_time:
                    recent_in_minute[addr] = last_seen

            # Update the stored timestamps
            self.address_timestamps = defaultdict(float, recent_in_minute)

        # Update display
        if recent_in_minute:
            # Sort by most recently seen
            sorted_addresses = sorted(recent_in_minute.items(), key=lambda x: x[1], reverse=True)
            address_list = [addr for addr, _ in sorted_addresses]
            self.address_display.setText("\n".join(address_list))
        else:
            self.address_display.setText("(no recent messages)")

    def start_recording(self, session_dir):
        """Start recording OSC messages to CSV."""
        self.session_dir = session_dir
        self.recording = True

        # Reset message counter
        self.message_count_label.setText("Messages received: 0")

    def stop_recording(self):
        """Stop recording OSC messages."""
        if not self.recording:
            return
        self.recording = False
        self.session_dir = None

    def closeEvent(self, event):
        """Clean shutdown when panel is closed."""
        self.stop_recording()
        if self.server:
            self.server.stop_all()
            self.server.terminate_server()
            self.server.join_server()
        super().closeEvent(event)
