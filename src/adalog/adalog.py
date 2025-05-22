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
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPalette
from datetime import datetime
from pathlib import Path


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

        self.apply_dark_mode()
        self.initUI()

    def apply_dark_mode(self):
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor(30, 30, 30))
        palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
        palette.setColor(QPalette.ColorRole.Base, QColor(45, 45, 45))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(60, 60, 60))
        QApplication.setPalette(palette)

        # Global font size style
        self.setStyleSheet(
            """
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
        """
        )

    def initUI(self):
        top_toolbar = QWidget()
        top_layout = QHBoxLayout()

        self.panel_selector = QComboBox()
        self.panel_selector.addItems(self.available_modalities.keys())
        self.panel_selector.setStyleSheet("background-color: #2d2d2d; color: white;")

        add_panel_btn = QPushButton("Add Panel")
        add_panel_btn.clicked.connect(self.add_panel)
        add_panel_btn.setStyleSheet("background-color: #3d3d3d; color: white;")

        self.user_field = QLineEdit()
        self.user_field.setPlaceholderText("User Name")
        self.user_field.setStyleSheet("background-color: #2d2d2d; color: white;")

        self.session_btn = QPushButton("Start Session")
        self.session_btn.clicked.connect(self.toggle_session)
        self.session_btn.setStyleSheet("background-color: #3d3d3d; color: white;")

        self.status_indicator = QLabel()
        self.update_status_indicator()

        top_layout.addWidget(self.panel_selector)
        top_layout.addWidget(add_panel_btn)
        top_layout.addWidget(self.user_field)
        top_layout.addWidget(self.session_btn)
        top_layout.addWidget(self.status_indicator)
        top_layout.addStretch()

        top_toolbar.setLayout(top_layout)
        self.setMenuWidget(top_toolbar)

        central_layout = QVBoxLayout()
        self.central_container = QWidget()
        self.central_container.setLayout(central_layout)
        self.setCentralWidget(self.central_container)

    def update_status_indicator(self):
        color = "#00ff00" if self.session_running else "#ff4444"
        self.status_indicator.setText("●")
        self.status_indicator.setStyleSheet(f"color: {color}; font-size: 18px;")

    def toggle_session(self):
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

            for dock in self.dock_widgets.values():
                widget = dock if isinstance(dock, QDockWidget) else dock
                if hasattr(widget, "start_recording"):
                    widget.start_recording(session_dir)

        else:
            for dock in self.dock_widgets.values():
                widget = dock if isinstance(dock, QDockWidget) else dock
                if hasattr(widget, "stop_recording"):
                    widget.stop_recording()

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
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock_widget)
            self.dock_widgets[panel_name] = panel_instance


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
