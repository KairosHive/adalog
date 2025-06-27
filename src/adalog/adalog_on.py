import hashlib
import importlib.util
import os
import sys
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QTime, QTimer
from PyQt6.QtGui import QColor, QPalette, QPixmap
from PyQt6.QtWidgets import QSizePolicy 
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    QCompleter,
)
from PyQt6.QtCore import QStringListModel


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Adalog Online Interface")
        self.setGeometry(100, 100, 800, 600)

        self.modalities_path = Path("modalities/on")
        self.available_modalities = self.load_modalities()
        self.dock_widgets: list[object] = []
        self.system_running = False
        self.chrono_label = QLabel("00:00")
        self.chrono_label.setStyleSheet("color: white; font-size: 18px;")
        self.chrono_timer = QTimer()
        self.chrono_timer.timeout.connect(self.update_chrono)
        self.system_start_time = None
        self.initUI()

    def initUI(self):
        # ───── Top toolbar layout ───────────────────────────────
        top_toolbar = QWidget()
        outer_top_layout = QVBoxLayout()
        outer_top_layout.setSpacing(5)
        outer_top_layout.setContentsMargins(5, 5, 5, 5)

        # ───── Row 0: centered logo ─────────────────────────────
        logo = QLabel()
        logo_path = Path(__file__).resolve().parent / "assets" / "logo.png"
        pix = QPixmap(str(logo_path))

        if not pix.isNull():
            scaled = pix.scaledToHeight(200, Qt.TransformationMode.SmoothTransformation)
            logo.setPixmap(scaled)
        else:
            logo.setText("logo.png not found")

        logo.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        outer_top_layout.addWidget(logo, alignment=Qt.AlignmentFlag.AlignHCenter)

        # ───── Row 1: Controls (Dropdown, Add Panel, …) ─────────
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(10)

        self.panel_selector = QComboBox()
        self.panel_selector.addItems(self.available_modalities.keys())
        self.panel_selector.setMinimumContentsLength(12)

        add_panel_btn = QPushButton("Add Panel")
        add_panel_btn.clicked.connect(self.add_panel)

        self.system_btn = QPushButton("Start System")
        self.system_btn.clicked.connect(self.toggle_system)

        self.status_indicator = QLabel()
        self.update_status_indicator()

        # Add widgets on the left
        controls_layout.addWidget(self.panel_selector)
        controls_layout.addWidget(add_panel_btn)
        controls_layout.addWidget(self.system_btn)

        # Group chrono + light together
        chrono_group = QHBoxLayout()
        chrono_group.setSpacing(5)
        chrono_group.addWidget(self.chrono_label)
        chrono_group.addWidget(self.status_indicator)

        chrono_widget = QWidget()
        chrono_widget.setLayout(chrono_group)

        controls_layout.addWidget(chrono_widget)

        controls_layout.addStretch()

        # Assemble the top bar
        outer_top_layout.addLayout(controls_layout)
        top_toolbar.setLayout(outer_top_layout)
        self.setMenuWidget(top_toolbar)

        # configure the main window
        self.setCentralWidget(None)
        self.setDockNestingEnabled(True)


    def update_status_indicator(self):
        color = "#00ff00" if self.system_running else "#ff4444"
        self.status_indicator.setText("●")
        self.status_indicator.setStyleSheet(f"color: {color}; font-size: 18px;")

    def toggle_system(self):
        # flip state ------------------------------------------------------------
        self.system_running = not self.system_running
        self.system_btn.setText("Stop System" if self.system_running else "Start System")
        self.update_status_indicator()

        # -----------------------------------------------------------------------
        if self.system_running:  # ------------- START ---------------
            self.system_start_time = datetime.utcnow()
            self.chrono_timer.start(1000)  # update every second
            self.chrono_label.setText("00:00")  # reset display

            # ←─  NEW LOOP: over every panel instance in the list
            for panel in self.dock_widgets:
                if hasattr(panel, "start"):
                    panel.start()


        else:  # ------------- STOP ----------------
            self.chrono_timer.stop()
            for panel in self.dock_widgets:
                if hasattr(panel, "stop"):
                    panel.stop()

    def update_chrono(self):
        if self.system_start_time:
            elapsed = datetime.utcnow() - self.system_start_time
            minutes, seconds = divmod(int(elapsed.total_seconds()), 60)
            self.chrono_label.setText(f"{minutes:02d}:{seconds:02d}")

    def load_modalities(self):
        import adalog.modalities.on  # Import the modalities package

        modalities_dir = Path(adalog.modalities.on.__file__).parent
        modalities = {}

        for file in modalities_dir.glob("*.py"):
            if file.stem == "__init__":
                continue

            module_name = f"adalog.modalities.on.{file.stem}"
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
        base_name = self.panel_selector.currentText()
        panel_class = self.available_modalities.get(base_name)
        if not panel_class:
            return

        # How many panels of this type already exist?
        count = sum(1 for p in self.dock_widgets if type(p).__name__ == base_name)
        title = base_name if count == 0 else f"{base_name}{count + 1}"

        dock_widget = QDockWidget(title, self)
        panel_instance = panel_class()

        dock_widget.setWidget(panel_instance)

        # colour = pastel_color_hex(base_name)
        colour = panel_colors.get(base_name, "#4488ff")  # Default to blue if not found
        dock_widget.setStyleSheet(
            f"""
            /* frame shown while the dock is floating ------------- */
            QDockWidget {{                     /* title-bar etc.   */
                background: #2d2d2d;
            }}
            QDockWidget::pane {{               /* floating frame   */
                border: 2px solid {colour};
                border-radius: 4px;
                margin: 0px;
            }}

            /* widget area shown when the dock is *docked* -------- */
            QDockWidget > QWidget {{           /* direct child     */
                border: 2px solid {colour};
                border-radius: 4px;
                background: transparent;       /* keep your dark theme */
            }}
            QDockWidget::title {{
                background:
                {colour};
                color: white;
                font-size: 32px;
                font-weight: bold;
                padding-left: 6px;
                height: 28px;
            }}
        """
        )

        self.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, dock_widget)
        self.dock_widgets.append(panel_instance)
        dock_widget.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        dock_widget.setFloating(False)

        # Remove panel from the list when the dock is closed
        dock_widget.destroyed.connect(lambda _, pi=panel_instance: self.dock_widgets.remove(pi))


def pastel_color_hex(text: str) -> str:
    h = hashlib.md5(text.encode()).digest()
    pastel = lambda b: 120 + (b % 130)  # 120-249 → pastel range
    r, g, b = pastel(h[0]), pastel(h[1]), pastel(h[2])
    return f"#{r:02x}{g:02x}{b:02x}"  # "#cbe6d5"


panel_colors = {
    "DreamIncubator": "#b157d1", # Using EEG color for now
}


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
                border: 1px solid #444444;
            }

            QComboBox QAbstractItemView {
                background-color: #2d2d2d;    /* same dark background */
                color: white;                 /* make dropdown text visible */
                selection-background-color: #555555;
                selection-color: white;
            }

            QDockWidget {
                font-size: 22px;
                background-color: #2d2d2d;
                color: black;
            }
            QTabBar {
                font-size: 18px;
                background-color: #2d2d2d;
                color: black;
            }
            QTextEdit {                /* <-- opened here */
                font-size: 18px;
                background-color: #2b2b2b;
                color: white;
            }                          /* <-- need this */

            /* Thin coloured outline around every dock-panel */
            QDockWidget::pane {
                border: 2px solid #4488ff;
                border-radius: 4px;
                margin: 0;
            }
            
            QDockWidget::title {
                font-size: 24px;        /* make the text larger           */
                padding-left: 6px;      /* breathing room before the text */
                height: 28px;           /* forces the bar to grow a bit   */
            }
        
        
        """
    app.setStyleSheet(styles)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="adalog online interface")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    set_theme(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
