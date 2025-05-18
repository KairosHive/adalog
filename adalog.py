import sys, os
from pathlib import Path
from threading import Thread
from goofi.manager import Manager
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QLabel, QRadioButton, QButtonGroup,
    QTextEdit, QColorDialog, QSpinBox, QComboBox,
)
from PyQt6.QtGui import (
    QPainter, QPen, QImage, QColor, QPixmap, QMouseEvent, QIcon
)
from pylsl import resolve_streams

from PyQt6.QtCore import Qt, QDateTime, pyqtSignal
from oscpy.client import OSCClient
from oscpy.server import OSCThreadServer
import pandas as pd
from datetime import datetime


# ── Subclass QTextEdit to emit on spacebar ────────────────────────────────────
class SpaceTextEdit(QTextEdit):
    spacePressed = pyqtSignal()
    def keyPressEvent(self, e):
        super().keyPressEvent(e)
        if e.key() == Qt.Key.Key_Space:
            self.spacePressed.emit()

# ── Dedicated Drawing Canvas with strokeFinished signal ──────────────────────
class DrawingCanvas(QLabel):
    strokeFinished = pyqtSignal()

    def __init__(self, width=975, height=415, parent=None):
        super().__init__(parent)
        self.setFixedSize(width, height)
        self.image = QImage(width, height, QImage.Format.Format_RGB32)
        self.penColor = QColor("black")
        self.penWidth = 2
        self.clear()
        self.drawing = False
        self.lastPoint = None

    def clear(self):
        self.image.fill(Qt.GlobalColor.white)
        self.setPixmap(QPixmap.fromImage(self.image))

    def mousePressEvent(self, e: QMouseEvent):
        if e.button() == Qt.MouseButton.LeftButton:
            self.drawing = True
            self.lastPoint = e.position().toPoint()

    def mouseMoveEvent(self, e: QMouseEvent):
        if self.drawing:
            painter = QPainter(self.image)
            pen = QPen(self.penColor, self.penWidth,
                      Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(self.lastPoint, e.position().toPoint())
            self.lastPoint = e.position().toPoint()
            self.setPixmap(QPixmap.fromImage(self.image))

    def mouseReleaseEvent(self, e: QMouseEvent):
        if self.drawing and e.button() == Qt.MouseButton.LeftButton:
            self.drawing = False
            # emit signal so parent can save
            self.strokeFinished.emit()

# ── Main Application ─────────────────────────────────────────────────────────
class AdalogApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(1000, 850)
        self.setWindowTitle("🧠 Adalog App")
        self.setWindowIcon(QIcon("assets/logo.png"))

        # Center the window on the screen
        screen_geometry = QApplication.primaryScreen().availableGeometry()
        x = (screen_geometry.width() - self.width()) // 2
        y = (screen_geometry.height() - self.height()) // 2
        self.move(x, y)


        # Build UI (initialize self.eeg_label)
        self.initUI()

        # OSC setup (after UI is built to avoid missing attributes)
        self.osc_client = OSCClient("127.0.0.1", 5005)
        self.osc_server = OSCThreadServer()
        self.osc_server.listen("127.0.0.1", 5006, default=True)
        self.osc_server.bind(b"/eeg_quality", self.update_eeg_quality)

        # State
        self.recording = False
        self.session_dir = None
        self.logged_word_index = 0

        # Hide drawing controls initially
        self.switch_mode()

    def initUI(self):
        self.setStyleSheet("""
            QLabel {
                font-size: 18px;
            }
            QLineEdit {
                font-size: 22px;
            }
            QPushButton {
                font-size: 18px;
            }
            QRadioButton {
                font-size: 18px;
            }
            QTextEdit {
                font-size: 18px;
            }
            QSpinBox {
                font-size: 18px;
            }
            QComboBox {
                font-size: 16px;
            }
        """)

        main = QVBoxLayout(self)

        # Add the logo at the top, centered and scaled
        logo_label = QLabel(self)
        logo_pixmap = QPixmap("assets/logo.png")

        # Use the actual image size, then scale it down with high quality
        target_size = 150
        scaled_pixmap = logo_pixmap.scaled(
            target_size, target_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        logo_label.setPixmap(scaled_pixmap)
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main.addWidget(logo_label)



        
        # Status indicator
        self.status_label = QLabel("● RECORDING OFF")
        self.status_label.setStyleSheet("color:red; font-weight:bold;")
        main.addWidget(self.status_label)

        # Subject ID
        subject_row = QHBoxLayout()
        self.subject_input = QLineEdit(placeholderText="Subject ID")
        self.subject_input.editingFinished.connect(self.update_session_types)
        subject_row.addWidget(QLabel("Subject ID:"))
        subject_row.addWidget(self.subject_input)
        main.addLayout(subject_row)

        # Mode radios with their own session type input
        mode_row = QHBoxLayout()

        # Text mode radio and session input
        self.text_rb = QRadioButton("Text Mode")
        self.text_rb.setChecked(True)
        self.text_session_input = QComboBox()
        self.text_session_input.setEditable(True)
        self.text_session_input.lineEdit().setPlaceholderText("Session Type (Text Mode)")

        text_mode_layout = QVBoxLayout()
        text_mode_layout.addWidget(self.text_rb)
        text_mode_layout.addWidget(self.text_session_input)
        mode_row.addLayout(text_mode_layout)

        # Drawing mode radio and session input
        self.draw_rb = QRadioButton("Drawing Mode")
        self.draw_session_input = QComboBox()
        self.draw_session_input.setEditable(True)
        self.draw_session_input.lineEdit().setPlaceholderText("Session Type (Drawing Mode)")

        draw_mode_layout = QVBoxLayout()
        draw_mode_layout.addWidget(self.draw_rb)
        draw_mode_layout.addWidget(self.draw_session_input)
        mode_row.addLayout(draw_mode_layout)

        # Mode button group
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.text_rb, 0)
        self.mode_group.addButton(self.draw_rb, 1)

        main.addLayout(mode_row)


        # EEG quality and LSL streams
        eeg_row = QHBoxLayout()

        # EEG Quality label
        self.eeg_label = QLabel("EEG Quality: Unknown")
        eeg_row.addWidget(self.eeg_label)

        # LSL Stream dropdown
        self.lsl_dropdown = QComboBox()
        self.lsl_dropdown.addItem("No streams available")
        self.lsl_dropdown.setFixedWidth(300)
        eeg_row.addWidget(self.lsl_dropdown)

        # Refresh button for LSL streams
        self.refresh_btn = QPushButton("🔄 Refresh Streams")
        self.refresh_btn.clicked.connect(self.refresh_lsl_streams)
        eeg_row.addWidget(self.refresh_btn)

        main.addLayout(eeg_row)


        # Text editor
        self.editor = SpaceTextEdit()
        self.editor.spacePressed.connect(self.on_space)
        main.addWidget(self.editor)

        # Drawing canvas
        # Drawing canvas
        self.canvas = DrawingCanvas()
        self.canvas.strokeFinished.connect(self.save_drawing)
        main.addWidget(self.canvas)


        # Drawing controls
        controls = QHBoxLayout()
        self.clear_btn = QPushButton("Clear Canvas")
        controls.addWidget(self.clear_btn)
        self.clear_btn.clicked.connect(self.canvas.clear)

        self.color_btn = QPushButton("Pen Color")
        controls.addWidget(self.color_btn)
        self.color_btn.clicked.connect(self.choose_color)

        # Separate label for pen size
        self.size_label = QLabel("Pen Size:")
        controls.addWidget(self.size_label)

        self.size_spin = QSpinBox()
        controls.addWidget(self.size_spin)
        self.size_spin.setRange(1, 50)
        self.size_spin.setValue(2)
        self.size_spin.valueChanged.connect(lambda v: setattr(self.canvas, "penWidth", v))

        main.addLayout(controls)


        # Start/Stop buttons
        row3 = QHBoxLayout()
        self.start_btn = QPushButton("🟢 Start Recording"); row3.addWidget(self.start_btn)
        self.stop_btn  = QPushButton("🔴 Stop Recording"); row3.addWidget(self.stop_btn)
        main.addLayout(row3)

        # Connect signals
        self.start_btn.clicked.connect(self.start_recording)
        self.stop_btn.clicked.connect(self.stop_recording)
        self.mode_group.buttonClicked.connect(self.switch_mode)
        


    def choose_color(self):
        color = QColorDialog.getColor(initial=self.canvas.penColor, parent=self)
        if color.isValid():
            self.canvas.penColor = color
            self.color_btn.setStyleSheet(f"background-color:{color.name()};")

    def start_recording(self):
        sid = self.subject_input.text().strip()

        if self.mode_group.checkedId() == 0:  # Text Mode
            mode = "TextMode"
            stype = self.text_session_input.currentText().strip()
        else:  # Drawing Mode
            mode = "DrawingMode"
            stype = self.draw_session_input.currentText().strip()

        if not sid or not stype:
            print("Subject ID and Session Type must be provided.")
            return

        # Base session path
        base = Path("sessions") / sid / mode / stype
        ts = datetime.utcnow().isoformat().replace(":", "-").replace(".", "-")
        session_folder = base / ts
        session_folder.mkdir(parents=True, exist_ok=True)

        # Create drawings folder only for DrawingMode
        if mode == "DrawingMode":
            (session_folder / "drawings").mkdir(exist_ok=True)

        self.session_dir = str(session_folder)
        self.recording = True
        self.logged_word_index = 0
        self.editor.clear()
        self.canvas.clear()

        # Send full path of the recording directory
        self.osc_client.send_message(
            b"/recording_path",
            [str(session_folder / "neuro.csv").encode()]
        )

        self.status_label.setText("● RECORDING ON")
        self.status_label.setStyleSheet("color:green; font-weight:bold;")

        self.osc_client.send_message(b"/recording_start", [1])


    def update_session_types(self):
        sid = self.subject_input.text().strip()
        base_dir = Path("sessions") / sid

        # Clear existing items
        self.text_session_input.clear()
        self.draw_session_input.clear()

        text_modes = set()
        draw_modes = set()

        # Scan for existing modes and session types
        if base_dir.exists():
            for mode_dir in base_dir.iterdir():
                if mode_dir.is_dir():
                    for session_dir in mode_dir.iterdir():
                        if session_dir.is_dir():
                            if mode_dir.name == "TextMode":
                                text_modes.add(session_dir.name)
                            elif mode_dir.name == "DrawingMode":
                                draw_modes.add(session_dir.name)

        # Populate dropdowns
        self.text_session_input.addItems(sorted(text_modes))
        self.draw_session_input.addItems(sorted(draw_modes))

        # Allow users to type new entries
        self.text_session_input.setEditable(True)
        self.draw_session_input.setEditable(True)


    def stop_recording(self):
        self.recording = False
        self.status_label.setText("● RECORDING OFF")
        self.status_label.setStyleSheet("color:red; font-weight:bold;")
        # send OSC message /recording to 0
        self.osc_client.send_message(b"/recording_stop", [1])

    def refresh_lsl_streams(self):
        streams = resolve_streams()
        self.lsl_dropdown.clear()
        if not streams:
            self.lsl_dropdown.addItem("No streams available")
        else:
            for stream in streams:
                source_id = stream.source_id()
                name = stream.name()
                hostname = stream.hostname()
                self.lsl_dropdown.addItem(f"{source_id} ({name} @ {hostname})")

    def switch_mode(self):
        if self.mode_group.checkedId() == 0:  # Text Mode
            self.editor.show()
            self.canvas.hide()
            self.clear_btn.hide()
            self.color_btn.hide()
            self.size_label.hide()
            self.size_spin.hide()
            self.text_session_input.setEnabled(True)
            self.draw_session_input.setEnabled(False)
        else:  # Drawing Mode
            self.editor.hide()
            self.canvas.show()
            self.clear_btn.show()
            self.color_btn.show()
            self.size_label.show()
            self.size_spin.show()
            self.text_session_input.setEnabled(False)
            self.draw_session_input.setEnabled(True)



    def update_eeg_quality(self, quality):
        # Make sure the value is treated as a float
        if isinstance(quality, (bytes, bytearray)):
            quality = float(quality.decode())

        # Map the numerical value to a meaningful status
        if quality == 0:
            status = "Disconnected"
            color = "red"
        elif quality == 1:
            status = "Bad Signal"
            color = "orange"
        elif quality == 2:
            status = "Good Signal"
            color = "green"
        else:
            status = "Unknown"
            color = "gray"

        # Update the EEG quality display
        self.eeg_label.setText(f"EEG Quality: {status}")
        self.eeg_label.setStyleSheet(f"color:{color}; font-weight:bold;")


    def on_space(self):
        if not self.recording:
            return
        text = self.editor.toPlainText().strip()
        words = text.split()
        if len(words) > self.logged_word_index:
            w = words[self.logged_word_index]
            ts = datetime.utcnow().isoformat()
            csv_path = os.path.join(self.session_dir, "pheno.csv")
            pd.DataFrame([[ts, w]], columns=["timestamp","content"]).to_csv(
                csv_path, mode="a",
                header=not os.path.exists(csv_path),
                index=False
            )
            self.osc_client.send_message(b"/word",[w.encode()])
            self.logged_word_index += 1

    def save_drawing(self):
        # Only save drawings if the session directory and "drawings" folder exist
        if self.recording and self.session_dir and "DrawingMode" in self.session_dir:
            ts = datetime.utcnow().isoformat().replace(":", "-").replace(".", "-")
            fn = os.path.join(self.session_dir, "drawings", f"{ts}.png")
            self.canvas.image.save(fn)


    def closeEvent(self, _):
        self.osc_server.terminate_server()
        self.osc_server.join_server()

if __name__ == "__main__":
    gfi = Thread(target=Manager, kwargs=dict(filepath=Path(__file__).parent / "adalog.gfi", headless=True), daemon=True)
    gfi.start()

    app = QApplication(sys.argv)
    window = AdalogApp()
    window.show()
    sys.exit(app.exec())
