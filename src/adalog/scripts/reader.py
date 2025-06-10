import random
import sys
import time
from datetime import datetime
from typing import List, Optional

from oscpy.client import OSCClient
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPalette, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class WordReaderWidget(QMainWindow):
    """Main widget for the word reader application."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Flashing Word Reader")
        self.setGeometry(100, 100, 800, 600)

        # State variables
        self.words: List[str] = []
        self.current_word_index = 0
        self.is_running = False
        self.is_paused = False
        self.osc_client: Optional[OSCClient] = None

        # Timers
        self.word_timer = QTimer()
        self.word_timer.timeout.connect(self._next_word)

        # UI setup
        self._setup_ui()

    def _setup_ui(self):
        """Setup the user interface."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Create stacked widget to switch between setup and reading modes
        self.stacked_widget = QStackedWidget()
        central_widget_layout = QVBoxLayout(central_widget)
        central_widget_layout.addWidget(self.stacked_widget)

        # Setup page
        self._create_setup_page()

        # Reading pages (flash mode and highlight mode)
        self._create_flash_page()
        self._create_highlight_page()

    def _create_setup_page(self):
        """Create the initial setup page."""
        setup_widget = QWidget()
        layout = QVBoxLayout(setup_widget)

        # Title
        title = QLabel("Flashing Word Reader Setup")
        title.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # Text input
        layout.addWidget(QLabel("Enter text to read:"))
        self.text_input = QTextEdit()
        self.text_input.setPlainText(
            "This is a sample text for the flashing word reader. You can replace this with any text you want to read word by word."
        )
        layout.addWidget(self.text_input)

        # Settings grid
        settings_layout = QVBoxLayout()

        # OSC Port
        osc_layout = QHBoxLayout()
        osc_layout.addWidget(QLabel("OSC Port:"))
        self.osc_port_spinbox = QSpinBox()
        self.osc_port_spinbox.setRange(1024, 65535)
        self.osc_port_spinbox.setValue(8000)
        osc_layout.addWidget(self.osc_port_spinbox)
        osc_layout.addStretch()
        settings_layout.addLayout(osc_layout)

        # Reading mode
        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("Reading Mode:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Flash Mode", "Highlight Mode"])
        mode_layout.addWidget(self.mode_combo)
        mode_layout.addStretch()
        settings_layout.addLayout(mode_layout)

        # Word interval
        interval_layout = QHBoxLayout()
        interval_layout.addWidget(QLabel("Word Interval (ms):"))
        self.interval_spinbox = QSpinBox()
        self.interval_spinbox.setRange(100, 5000)
        self.interval_spinbox.setValue(500)
        self.interval_spinbox.setSuffix(" ms")
        interval_layout.addWidget(self.interval_spinbox)
        interval_layout.addStretch()
        settings_layout.addLayout(interval_layout)

        # Jitter
        jitter_layout = QHBoxLayout()
        jitter_layout.addWidget(QLabel("Jitter (ms):"))
        self.jitter_spinbox = QSpinBox()
        self.jitter_spinbox.setRange(0, 1000)
        self.jitter_spinbox.setValue(0)
        self.jitter_spinbox.setSuffix(" ms")
        jitter_layout.addWidget(self.jitter_spinbox)
        jitter_layout.addStretch()
        settings_layout.addLayout(jitter_layout)

        layout.addLayout(settings_layout)

        # Start button
        self.start_button = QPushButton("Start Reading")
        self.start_button.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        self.start_button.clicked.connect(self._start_reading)
        layout.addWidget(self.start_button)

        self.stacked_widget.addWidget(setup_widget)

    def _create_flash_page(self):
        """Create the flash mode page."""
        flash_widget = QWidget()
        flash_widget.setStyleSheet("background-color: black;")
        layout = QVBoxLayout(flash_widget)

        # Controls at top
        controls_layout = QHBoxLayout()
        controls_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self.flash_pause_button = QPushButton("Pause")
        self.flash_pause_button.clicked.connect(self._toggle_pause)
        controls_layout.addWidget(self.flash_pause_button)

        controls_layout.addWidget(QLabel("Interval:"))
        self.flash_interval_slider = QSlider(Qt.Orientation.Horizontal)
        self.flash_interval_slider.setRange(100, 2000)
        self.flash_interval_slider.setValue(500)
        self.flash_interval_slider.valueChanged.connect(self._update_interval)
        self.flash_interval_slider.setMaximumWidth(200)
        controls_layout.addWidget(self.flash_interval_slider)

        self.flash_interval_label = QLabel("500ms")
        self.flash_interval_label.setStyleSheet("color: white;")
        controls_layout.addWidget(self.flash_interval_label)

        stop_button = QPushButton("Stop")
        stop_button.clicked.connect(self._stop_reading)
        controls_layout.addWidget(stop_button)

        controls_layout.addStretch()
        layout.addLayout(controls_layout)

        # Large word display
        self.flash_word_label = QLabel("")
        self.flash_word_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.flash_word_label.setFont(QFont("Arial", 48, QFont.Weight.Bold))
        self.flash_word_label.setStyleSheet("color: white; background-color: black;")
        layout.addWidget(self.flash_word_label, 1)  # Stretch to fill space

        self.stacked_widget.addWidget(flash_widget)

    def _create_highlight_page(self):
        """Create the highlight mode page."""
        highlight_widget = QWidget()
        highlight_widget.setStyleSheet("background-color: black;")
        layout = QVBoxLayout(highlight_widget)

        # Controls at top
        controls_layout = QHBoxLayout()
        controls_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self.highlight_pause_button = QPushButton("Pause")
        self.highlight_pause_button.clicked.connect(self._toggle_pause)
        controls_layout.addWidget(self.highlight_pause_button)

        controls_layout.addWidget(QLabel("Interval:"))
        self.highlight_interval_slider = QSlider(Qt.Orientation.Horizontal)
        self.highlight_interval_slider.setRange(100, 2000)
        self.highlight_interval_slider.setValue(500)
        self.highlight_interval_slider.valueChanged.connect(self._update_interval)
        self.highlight_interval_slider.setMaximumWidth(200)
        controls_layout.addWidget(self.highlight_interval_slider)

        self.highlight_interval_label = QLabel("500ms")
        self.highlight_interval_label.setStyleSheet("color: white;")
        controls_layout.addWidget(self.highlight_interval_label)

        stop_button = QPushButton("Stop")
        stop_button.clicked.connect(self._stop_reading)
        controls_layout.addWidget(stop_button)

        controls_layout.addStretch()
        layout.addLayout(controls_layout)

        # Scrollable text area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet("background-color: black;")

        self.highlight_text_widget = QTextEdit()
        self.highlight_text_widget.setReadOnly(True)
        self.highlight_text_widget.setFont(QFont("Arial", 18))
        self.highlight_text_widget.setFrameStyle(QFrame.Shape.NoFrame)
        self.highlight_text_widget.setStyleSheet("background-color: black; color: white;")

        scroll_area.setWidget(self.highlight_text_widget)
        layout.addWidget(scroll_area, 1)

        self.stacked_widget.addWidget(highlight_widget)

    def _start_reading(self):
        """Start the reading session."""
        # Get text and split into words
        text = self.text_input.toPlainText().strip()
        if not text:
            return

        self.words = text.split()
        self.current_word_index = 0
        self.is_running = True
        self.is_paused = False

        # Setup OSC client
        try:
            self.osc_client = OSCClient("127.0.0.1", self.osc_port_spinbox.value())
        except Exception as e:
            print(f"Could not create OSC client: {e}")
            self.osc_client = None

        # Switch to appropriate reading mode
        mode = self.mode_combo.currentText()
        if mode == "Flash Mode":
            self.stacked_widget.setCurrentIndex(1)
            self._setup_flash_mode()
        else:
            self.stacked_widget.setCurrentIndex(2)
            self._setup_highlight_mode()

        # Start the timer
        self._update_timer_interval()
        self.word_timer.start()

    def _setup_flash_mode(self):
        """Setup flash mode specific elements."""
        self.flash_interval_slider.setValue(self.interval_spinbox.value())
        self.flash_interval_label.setText(f"{self.interval_spinbox.value()}ms")

    def _setup_highlight_mode(self):
        """Setup highlight mode specific elements."""
        self.highlight_interval_slider.setValue(self.interval_spinbox.value())
        self.highlight_interval_label.setText(f"{self.interval_spinbox.value()}ms")

        # Set up the text with highlighting capability
        self.highlight_text_widget.setPlainText(" ".join(self.words))

    def _next_word(self):
        """Advance to the next word."""
        if not self.is_running or self.is_paused or self.current_word_index >= len(self.words):
            return

        current_word = self.words[self.current_word_index]

        # Send OSC message
        self._send_osc_word(current_word)

        # Update display based on mode
        current_mode = self.stacked_widget.currentIndex()
        if current_mode == 1:  # Flash mode
            self._update_flash_display(current_word)
        elif current_mode == 2:  # Highlight mode
            self._update_highlight_display()

        self.current_word_index += 1

        # Check if we've reached the end AFTER incrementing
        if self.current_word_index >= len(self.words):
            # Wait a bit before stopping to let the last word be seen
            QTimer.singleShot(self.word_timer.interval(), self._stop_reading)
            return

        # Update timer interval with jitter
        self._update_timer_interval()

    def _update_flash_display(self, word: str):
        """Update the flash mode display."""
        self.flash_word_label.setText(word)

        # Clear the word after a short display time
        QTimer.singleShot(min(200, self.word_timer.interval() // 2), lambda: self.flash_word_label.setText(""))

    def _update_highlight_display(self):
        """Update the highlight mode display."""
        # Clear previous highlights and reset to normal formatting
        cursor = self.highlight_text_widget.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        normal_format = QTextCharFormat()
        normal_format.setBackground(QColor())  # Clear background (transparent)
        normal_format.setForeground(QColor("lightgray"))  # Light gray for normal text
        normal_format.setFontWeight(QFont.Weight.Normal)  # Normal weight
        cursor.mergeCharFormat(normal_format)

        # Find and highlight current word
        words_before = " ".join(self.words[: self.current_word_index])
        start_pos = len(words_before) + (1 if words_before else 0)
        end_pos = start_pos + len(self.words[self.current_word_index])

        # Highlight current word with subtle colored background and bright white text
        cursor = self.highlight_text_widget.textCursor()
        cursor.setPosition(start_pos)
        cursor.setPosition(end_pos, QTextCursor.MoveMode.KeepAnchor)

        highlight_format = QTextCharFormat()
        highlight_format.setBackground(QColor(70, 130, 180))  # Steel blue background
        highlight_format.setForeground(QColor("white"))  # Bright white text
        highlight_format.setFontWeight(QFont.Weight.Normal)  # Keep normal weight to prevent shifting
        cursor.mergeCharFormat(highlight_format)

        # Center the highlighted word
        cursor.setPosition(start_pos)
        self.highlight_text_widget.setTextCursor(cursor)
        self.highlight_text_widget.ensureCursorVisible()

    def _send_osc_word(self, word: str):
        """Send the current word via OSC."""
        if self.osc_client:
            try:
                self.osc_client.send_message(b"/reader/word", [word.encode()])
            except Exception as e:
                print(f"OSC send error: {e}")

    def _toggle_pause(self):
        """Toggle pause state."""
        self.is_paused = not self.is_paused

        pause_buttons = [self.flash_pause_button, self.highlight_pause_button]
        for button in pause_buttons:
            button.setText("Play" if self.is_paused else "Pause")

        if self.is_paused:
            self.word_timer.stop()
        else:
            self.word_timer.start()

    def _update_interval(self, value):
        """Update the word interval from slider."""
        current_mode = self.stacked_widget.currentIndex()
        if current_mode == 1:  # Flash mode
            self.flash_interval_label.setText(f"{value}ms")
        elif current_mode == 2:  # Highlight mode
            self.highlight_interval_label.setText(f"{value}ms")

        self._update_timer_interval()

    def _update_timer_interval(self):
        """Update the timer interval with jitter."""
        if not self.is_running:
            return

        current_mode = self.stacked_widget.currentIndex()
        if current_mode == 1:  # Flash mode
            base_interval = self.flash_interval_slider.value()
        elif current_mode == 2:  # Highlight mode
            base_interval = self.highlight_interval_slider.value()
        else:
            base_interval = self.interval_spinbox.value()

        jitter = self.jitter_spinbox.value()
        if jitter > 0:
            actual_interval = base_interval + random.randint(-jitter // 2, jitter // 2)
        else:
            actual_interval = base_interval

        actual_interval = max(50, actual_interval)  # Minimum 50ms
        self.word_timer.setInterval(actual_interval)

    def _stop_reading(self):
        """Stop the reading session and return to setup."""
        self.is_running = False
        self.is_paused = False
        self.word_timer.stop()

        # Reset buttons
        self.flash_pause_button.setText("Pause")
        self.highlight_pause_button.setText("Pause")

        # Return to setup page
        self.stacked_widget.setCurrentIndex(0)

    def closeEvent(self, event):
        """Clean up when closing the application."""
        self._stop_reading()
        super().closeEvent(event)


def main():
    """Main function to run the word reader application."""
    app = QApplication(sys.argv)

    # Set application style
    app.setStyle("Fusion")

    # Create and show the main window
    window = WordReaderWidget()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
