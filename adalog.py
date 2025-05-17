import sys, os
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QLabel, QRadioButton, QButtonGroup,
    QTextEdit, QColorDialog, QSpinBox, QComboBox,
)
from PyQt6.QtGui import (
    QPainter, QPen, QImage, QColor, QPixmap, QMouseEvent,
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

    def __init__(self, width=600, height=400, parent=None):
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
        self.setWindowTitle("🧠 Adalog App")
        self.setGeometry(100, 100, 900, 700)

        # Build UI (initialize self.eeg_label)
        self.initUI()

        # OSC setup (after UI is built to avoid missing attributes)
        self.osc_client = OSCClient("127.0.0.1", 5005)
        osc_server = OSCThreadServer()
        osc_server.listen("127.0.0.1", 5006, default=True)
        osc_server.bind(b"/eeg_quality", self.update_eeg_quality)

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

        # Subject ID & Session Type
        row1 = QHBoxLayout()
        self.subject_input = QLineEdit(placeholderText="Subject ID")
        self.session_input = QLineEdit(placeholderText="Session Type")
        row1.addWidget(self.subject_input); row1.addWidget(self.session_input)
        main.addLayout(row1)

        # Mode radios
        self.mode_group = QButtonGroup(self)
        self.text_rb = QRadioButton("Text Mode"); self.text_rb.setChecked(True)
        self.draw_rb = QRadioButton("Drawing Mode")
        self.mode_group.addButton(self.text_rb, 0)
        self.mode_group.addButton(self.draw_rb, 1)
        row2 = QHBoxLayout(); row2.addWidget(self.text_rb); row2.addWidget(self.draw_rb)
        main.addLayout(row2)

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
        self.canvas = DrawingCanvas()
        # connect strokeFinished → save_png
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
        sid   = self.subject_input.text().strip()
        stype = self.session_input.text().strip()
        if not sid or not stype:
            return
        base = os.path.join("sessions", sid, stype)
        os.makedirs(base, exist_ok=True)
        ts = datetime.utcnow().isoformat().replace(":", "-").replace(".", "-")
        session_folder = os.path.join(base, ts)
        os.makedirs(os.path.join(session_folder, "drawings"), exist_ok=True)

        self.session_dir = session_folder
        self.recording   = True
        self.logged_word_index = 0
        self.editor.clear()
        self.canvas.clear()

        self.status_label.setText("● RECORDING ON")
        self.status_label.setStyleSheet("color:green; font-weight:bold;")
        # send OSC message /recording to 1
        self.osc_client.send_message(b"/recording_start", [1])

    def stop_recording(self):
        self.recording = False
        self.status_label.setText("● OFF")
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
            self.size_label.hide()  # Hide the "Pen Size:" label
            self.size_spin.hide()
        else:  # Drawing Mode
            self.editor.hide()
            self.canvas.show()
            self.clear_btn.show()
            self.color_btn.show()
            self.size_label.show()  # Show the "Pen Size:" label
            self.size_spin.show()


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
        # Called on every stroke finish
        if self.recording and self.session_dir:
            ts = datetime.utcnow().isoformat()
            fn = os.path.join(self.session_dir, "drawings", f"{ts}.png")
            self.canvas.image.save(fn)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = AdalogApp()
    window.show()
    sys.exit(app.exec())
