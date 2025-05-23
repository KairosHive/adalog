import sys
import os
import importlib.util
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QDockWidget,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QComboBox,
    QLabel,
    QLineEdit,
)
import hashlib

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPalette
from datetime import datetime
from pathlib import Path
from PyQt6.QtWidgets import QWidget, QLabel, QPushButton, QHBoxLayout
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLineEdit, QScrollArea, QVBoxLayout, QHBoxLayout, QFrame
import pandas as pd


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Adalog Main Interface")
        self.setGeometry(100, 100, 800, 600)

        self.modalities_path = Path("modalities")
        self.available_modalities = self.load_modalities()
        self.dock_widgets = {}
        self.session_running = False
        self.session_dir = None

        self.initUI()

    def initUI(self):
        # ───── Top toolbar layout ───────────────────────────────
        top_toolbar = QWidget()
        outer_top_layout = QVBoxLayout()
        outer_top_layout.setSpacing(5)
        outer_top_layout.setContentsMargins(5, 5, 5, 5)

        # ───── Top row: Controls (Dropdown, Add Panel, User Name, Session) ─────
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(10)

        self.panel_selector = QComboBox()
        self.panel_selector.addItems(self.available_modalities.keys())

        add_panel_btn = QPushButton("Add Panel")
        add_panel_btn.clicked.connect(self.add_panel)

        self.user_field = QLineEdit()
        self.user_field.setPlaceholderText("User Name")

        self.session_btn = QPushButton("Start Session")
        self.session_btn.clicked.connect(self.toggle_session)

        self.status_indicator = QLabel()
        self.update_status_indicator()

        controls_layout.addWidget(self.panel_selector)
        controls_layout.addWidget(add_panel_btn)
        controls_layout.addWidget(self.user_field)
        controls_layout.addWidget(self.session_btn)
        controls_layout.addWidget(self.status_indicator)
        controls_layout.addStretch()

        # ───── Second row: Tags ─────
        tags_row_layout = QHBoxLayout()
        tags_row_layout.setSpacing(5)

        self.tag_container = QHBoxLayout()  # holds tag widgets
        self.tag_container.setSpacing(5)
        self.tags = []

        self.tag_input = QLineEdit()
        self.tag_input.setPlaceholderText("Enter tags (press space or comma)")
        self.tag_input.returnPressed.connect(self.add_tag_from_input)
        self.tag_input.textEdited.connect(self.handle_text_edited)

        tags_row_layout.addLayout(self.tag_container)
        tags_row_layout.addWidget(self.tag_input)

        # Assemble top bar
        outer_top_layout.addLayout(controls_layout)
        outer_top_layout.addLayout(tags_row_layout)
        top_toolbar.setLayout(outer_top_layout)
        self.setMenuWidget(top_toolbar)

        # ───── Central widget where panels will dock ─────
        central_layout = QVBoxLayout()
        self.central_container = QWidget()
        self.central_container.setLayout(central_layout)
        self.setCentralWidget(self.central_container)

    def update_status_indicator(self):
        color = "#00ff00" if self.session_running else "#ff4444"
        self.status_indicator.setText("●")
        self.status_indicator.setStyleSheet(f"color: {color}; font-size: 18px;")

    def toggle_session(self):
        if not self.session_running:
            # Prevent starting if user name is empty
            user_name = self.user_field.text().strip()
            if not user_name:
                self.statusBar().showMessage("Please enter a User Name before starting the session.", 5000)
                return

        self.session_running = not self.session_running
        self.session_btn.setText("Stop Session" if self.session_running else "Start Session")
        self.update_status_indicator()

        if self.session_running:
            # Generate new unique session directory on start
            base_dir = os.path.join("sessions", self.user_field.text().strip())
            timestamp = datetime.utcnow().isoformat().replace(":", "-").replace(".", "-")
            session_dir = os.path.join(base_dir, timestamp)
            os.makedirs(session_dir, exist_ok=True)

            # Store this in case you want to access it later
            self.current_session_dir = session_dir

            self.save_tags_metadata()

            for dock in self.dock_widgets.values():
                widget = dock if isinstance(dock, QDockWidget) else dock
                if hasattr(widget, "start_recording"):
                    widget.start_recording(session_dir)

        else:
            for dock in self.dock_widgets.values():
                widget = dock if isinstance(dock, QDockWidget) else dock
                if hasattr(widget, "stop_recording"):
                    widget.stop_recording()

    def handle_text_edited(self, text):
        if text.endswith(" ") or text.endswith(","):
            self.add_tag_from_input()

    def add_tag_from_input(self):
        text = self.tag_input.text().strip(" ,")
        if text and text not in self.tags:
            self.tags.append(text)
            tag_label = TagLabel(text, self.remove_tag)
            self.tag_container.addWidget(tag_label)
            self.save_tags_metadata()  # ← save on add
        self.tag_input.clear()

    def remove_tag(self, tag_widget):
        tag_text = tag_widget.tag_text
        if tag_text in self.tags:
            self.tags.remove(tag_text)
            self.save_tags_metadata()  # ← save on remove

    def load_modalities(self):
        import adalog.modalities  # Import the modalities package

        modalities_dir = Path(adalog.modalities.__file__).parent
        modalities = {}

        for file in modalities_dir.glob("*.py"):
            if file.stem == "__init__":
                continue

            module_name = f"adalog.modalities.{file.stem}"
            try:
                module = importlib.import_module(module_name)
                class_name = "".join([part.capitalize() for part in file.stem.split("_")])
                modality_class = getattr(module, class_name, None)
                if modality_class:
                    modalities[class_name] = modality_class
            except Exception as e:
                print(f"Failed to load {module_name}: {e}")

        return modalities

    def save_tags_metadata(self):
        if not self.session_running or not self.current_session_dir:
            return

        csv_path = os.path.join(self.current_session_dir, "tags.csv")
        timestamp = datetime.utcnow().isoformat()

        # Prepare a row: timestamp + comma-separated tags
        row = [timestamp, ", ".join(self.tags)]

        # Write header only if file doesn't exist
        write_header = not os.path.exists(csv_path)

        df = pd.DataFrame([row], columns=["timestamp", "tags"])
        df.to_csv(csv_path, mode="a", header=write_header, index=False)

    def add_panel(self):
        panel_name = self.panel_selector.currentText()
        if panel_name in self.dock_widgets:
            return

        panel_class = self.available_modalities.get(panel_name)
        if panel_class:
            dock_widget = QDockWidget(panel_name, self)
            panel_instance = panel_class()
            dock_widget.setWidget(panel_instance)
            dock_widget.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
            dock_widget.setFloating(False)
            dock_widget.destroyed.connect(lambda: self.dock_widgets.pop(panel_name, None))
            self.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, dock_widget)
            self.dock_widgets[panel_name] = panel_instance


def pastel_color_from_text(text):
    # Create a hash from the text
    hash_bytes = hashlib.md5(text.encode()).digest()

    # Use the first 3 bytes for RGB and map to pastel
    def pastel(byte):
        return 120 + (byte % 130)  # [180–239]

    r, g, b = pastel(hash_bytes[0]), pastel(hash_bytes[1]), pastel(hash_bytes[2])

    return f"background-color: rgb({r},{g},{b});"


class TagLabel(QWidget):
    def __init__(self, tag_text, on_remove):
        super().__init__()
        self.tag_text = tag_text
        self.on_remove = on_remove

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)  # overall tag container spacing
        layout.setSpacing(4)

        self.label = QLabel(tag_text)
        self.label.setStyleSheet(
            """
            color: black;
            font-weight: bold;
            padding-left: 8px;
            padding-right: 8px;
            padding-top: 4px;
            padding-bottom: 4px;
        """
        )

        self.btn = QPushButton("×")
        self.btn.setFixedSize(16, 16)
        self.btn.setStyleSheet(
            """

        """
        )
        self.btn.clicked.connect(self.remove_self)

        layout.addWidget(self.label)
        layout.addWidget(self.btn)

        pastel_style = pastel_color_from_text(tag_text)
        self.setStyleSheet(
            f"""
            QWidget {{
                {pastel_style}
                border-radius: 10px;
            }}
        """
        )

    def remove_self(self):
        self.on_remove(self)
        self.deleteLater()


def set_theme(app: QApplication):
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(30, 30, 30))
    palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.Base, QColor(45, 45, 45))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(60, 60, 60))
    app.setPalette(palette)

    styles = """
            QLabel {
                font-size: 18px;
                color: white;
            }
            QLineEdit {
                font-size: 18px;
                background-color: #2d2d2d;
                color: white;
            }
            QPushButton {
                font-size: 18px;
                background-color: #3d3d3d;
                color: white;
            }
            QComboBox {
                font-size: 18px;
                background-color: #2d2d2d;
                color: white;
            }
            QDockWidget {
                font-size: 18px;
                background-color: #2d2d2d;
                color: white;
            }
            QTabBar {
                font-size: 18px;
                background-color: #2d2d2d;
                color: black;
            }
            QTextEdit {
                font-size: 18px;
                background-color: #2b2b2b;
                color: white;
            }
        """
    app.setStyleSheet(styles)


def main():
    app = QApplication(sys.argv)
    set_theme(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
