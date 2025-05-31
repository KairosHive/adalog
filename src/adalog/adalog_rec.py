import hashlib
import importlib.util
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
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
    def __init__(self, session_dir: str = "sessions"):
        super().__init__()
        self.session_dir = session_dir

        self.setWindowTitle("Adalog Main Interface")
        self.setGeometry(100, 100, 800, 600)

        self.modalities_path = Path("modalities/rec")
        self.available_modalities = self.load_modalities()
        self.dock_widgets: list[object] = []
        self.session_running = False
        self.chrono_label = QLabel("00:00")
        self.chrono_label.setStyleSheet("color: white; font-size: 18px;")
        self.chrono_timer = QTimer()
        self.chrono_timer.timeout.connect(self.update_chrono)
        self.session_start_time = None
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

        add_panel_btn = QPushButton("Add Panel")
        add_panel_btn.clicked.connect(self.add_panel)

        self.user_field = QLineEdit()
        self.user_field.setPlaceholderText("User Name")

        self.session_btn = QPushButton("Start Session")
        self.session_btn.clicked.connect(self.toggle_session)

        self.status_indicator = QLabel()
        self.update_status_indicator()

        # Add widgets on the left
        controls_layout.addWidget(self.panel_selector)
        controls_layout.addWidget(add_panel_btn)
        controls_layout.addWidget(self.user_field)
        controls_layout.addWidget(self.session_btn)

        # Group chrono + light together
        chrono_group = QHBoxLayout()
        chrono_group.setSpacing(5)
        chrono_group.addWidget(self.chrono_label)
        chrono_group.addWidget(self.status_indicator)

        chrono_widget = QWidget()
        chrono_widget.setLayout(chrono_group)

        controls_layout.addWidget(chrono_widget)

        controls_layout.addStretch()

        # --- Row 2: tags ------------------------------------------------------
        tags_row_layout = QHBoxLayout()
        tags_row_layout.setSpacing(5)

        # A QWidget that actually holds the TagLabel widgets
        self.tags_widget   = QWidget()
        self.tag_container = QHBoxLayout(self.tags_widget)
        self.tag_container.setSpacing(5)
        self.tag_container.setContentsMargins(0, 0, 0, 0)
        self.tags = []  

        # Scroll area wrapping that widget
        self.tag_scroll = QScrollArea()
        self.tag_scroll.setWidgetResizable(True)
        self.tag_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.tag_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tag_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.tag_scroll.setWidget(self.tags_widget)
        self.tag_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.tag_scroll.setStyleSheet("""
            QScrollArea { border: none; padding: 0px; }
            QScrollBar:horizontal {
            height: 6px;
            margin: 0px;
            background: transparent;
            }
        """)

        # Tags label
        tags_label = QLabel("Tags:")

        # Editable combo-box for new tags
        self.tag_input = QComboBox()
        self.tag_input.setEditable(True)
        self.tag_input.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.tag_input.setPlaceholderText("Enter tags (press space, comma, or pick from list)")
        self.tag_input.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.tag_input.setMaximumWidth(200)

        line_edit = self.tag_input.lineEdit()
        line_edit.returnPressed.connect(self.add_tag_from_input)
        line_edit.textEdited.connect(self.handle_text_edited)

        self.completer = QCompleter()
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.tag_input.setCompleter(self.completer)
        self.user_field.editingFinished.connect(self.update_tag_completer)

        tags_row_layout.addWidget(tags_label)
        tags_row_layout.addWidget(self.tag_input, 0)
        tags_row_layout.addWidget(self.tag_scroll, 1)

        # Assemble the top bar
        outer_top_layout.addLayout(controls_layout)
        outer_top_layout.addLayout(tags_row_layout)
        top_toolbar.setLayout(outer_top_layout)
        self.setMenuWidget(top_toolbar)

        # ───── central widget where panels will dock ────────────
        central_layout = QVBoxLayout()
        self.central_container = QWidget()
        self.central_container.setLayout(central_layout)
        self.setCentralWidget(self.central_container)

    def update_status_indicator(self):
        color = "#00ff00" if self.session_running else "#ff4444"
        self.status_indicator.setText("●")
        self.status_indicator.setStyleSheet(f"color: {color}; font-size: 18px;")

    def get_all_tags_for_user(self, user):
        tag_set = set()
        user_dir = os.path.join(self.session_dir, user)
        if not os.path.isdir(user_dir):
            return []
        for session_name in os.listdir(user_dir):
            tag_path = os.path.join(user_dir, session_name, "tags.csv")
            if os.path.isfile(tag_path):
                try:
                    df = pd.read_csv(tag_path)
                    if not df.empty and "tags" in df.columns:
                        for tag_str in df["tags"]:
                            if not isinstance(tag_str, str):
                                continue
                            for tag in tag_str.split(","):
                                t = tag.strip()
                                if t:
                                    tag_set.add(t)
                except Exception as e:
                    print(f"Could not read {tag_path}: {e}")
        return sorted(tag_set)

    def update_tag_completer(self):
        user = self.user_field.text().strip()
        if not user:
            self.tag_input.clear()
            return
        tag_list = self.get_all_tags_for_user(user)
        self.tag_input.clear()
        self.tag_input.addItems(tag_list)
        self.tag_input.setCurrentText("")
        # Still use QCompleter for typing!
        completer = QCompleter(tag_list)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.tag_input.setCompleter(completer)


    def toggle_session(self):
        if not self.session_running:
            # block start if user name is empty
            user_name = self.user_field.text().strip()
            if not user_name:
                self.statusBar().showMessage("Please enter a User Name before starting the session.", 5000)
                return

        # flip state ------------------------------------------------------------
        self.session_running = not self.session_running
        self.session_btn.setText("Stop Session" if self.session_running else "Start Session")
        self.update_status_indicator()

        # -----------------------------------------------------------------------
        if self.session_running:  # ------------- START ---------------
            base_dir = os.path.join(self.session_dir, self.user_field.text().strip())
            timestamp = datetime.utcnow().isoformat().replace(":", "-").replace(".", "-")
            session_dir = os.path.join(base_dir, timestamp)
            os.makedirs(session_dir, exist_ok=True)

            self.current_session_dir = session_dir
            self.save_tags_metadata()

            self.session_start_time = datetime.utcnow()
            self.chrono_timer.start(1000)  # update every second
            self.chrono_label.setText("00:00")  # reset display

            # ←─  NEW LOOP: over every panel instance in the list
            for panel in self.dock_widgets:
                if hasattr(panel, "start_recording"):
                    panel_name = type(panel).__name__          # e.g. "Eeg"
                    panel_dir = os.path.join(session_dir, panel_name)
                    os.makedirs(panel_dir, exist_ok=True)
                    panel.start_recording(panel_dir)


        else:  # ------------- STOP ----------------
            self.chrono_timer.stop()
            for panel in self.dock_widgets:
                if hasattr(panel, "stop_recording"):
                    panel.stop_recording()

    def handle_text_edited(self, text):
        if text.endswith(" ") or text.endswith(","):
            self.add_tag_from_input()

    def update_chrono(self):
        if self.session_start_time:
            elapsed = datetime.utcnow() - self.session_start_time
            minutes, seconds = divmod(int(elapsed.total_seconds()), 60)
            self.chrono_label.setText(f"{minutes:02d}:{seconds:02d}")

    def add_tag_from_input(self):
        text = self.tag_input.currentText().strip(" ,")
        if text and text not in self.tags:
            self.tags.append(text)
            tag_label = TagLabel(text, self.remove_tag)
            self.tag_container.addWidget(tag_label)
            self.save_tags_metadata()
            self.update_tag_completer()
        self.tag_input.setCurrentText("")


    def remove_tag(self, tag_widget):
        tag_text = tag_widget.tag_text
        if tag_text in self.tags:
            self.tags.remove(tag_text)
            self.save_tags_metadata()  # ← save on remove

    def load_modalities(self):
        import adalog.modalities.rec  # Import the modalities package

        modalities_dir = Path(adalog.modalities.rec.__file__).parent
        modalities = {}

        for file in modalities_dir.glob("*.py"):
            if file.stem == "__init__":
                continue

            module_name = f"adalog.modalities.rec.{file.stem}"
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

        self.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, dock_widget)
        self.dock_widgets.append(panel_instance)


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
        # stop this widget from expanding horizontally
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        # ─── outer layout (transparent) ──────────────────────────────────────
        outer_layout = QHBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        # ─── container widget (the actual pill) ──────────────────────────────
        container = QWidget()
        pastel_style = pastel_color_from_text(tag_text)
        container.setObjectName("tagPill")
        container.setStyleSheet(
            f"""
            QWidget#tagPill {{
                {pastel_style}
                border-radius: 12px;
            }}
        """
        )

        # ─── inner layout (inside the pill) ──────────────────────────────────
        inner_layout = QHBoxLayout(container)
        inner_layout.setContentsMargins(8, 2, 8, 2)
        inner_layout.setSpacing(4)

        # label (left side)
        label = QLabel(tag_text)
        label.setStyleSheet(
            f"""
            QLabel {{
                color: black;
                font-weight: bold;
            }}
        """
        )

        # close button (right side) – transparent, no extra rectangle
        close = QPushButton("×")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setFixedSize(20, 20)
        close.setStyleSheet(
            """
            QPushButton {
                background: transparent;
                border: none;
                color: black;
                font-weight: bold;
                padding: 0;
                margin: 0;
            }
            QPushButton:hover {
                background: #f0f0f0;
                border-radius: 10px;
            }
        """
        )
        close.clicked.connect(self.remove_self)

        inner_layout.addWidget(label)
        inner_layout.addWidget(close)
        outer_layout.addWidget(container)

    def remove_self(self):
        self.on_remove(self)
        self.deleteLater()


def pastel_color_hex(text: str) -> str:
    h = hashlib.md5(text.encode()).digest()
    pastel = lambda b: 120 + (b % 130)  # 120-249 → pastel range
    r, g, b = pastel(h[0]), pastel(h[1]), pastel(h[2])
    return f"#{r:02x}{g:02x}{b:02x}"  # "#cbe6d5"


panel_colors = {
    "Audio": "#5579d4",
    "Text": "#8ad38a",
    "Midi": "#deb865",
    "Eeg": "#b157d1",
    "Meteo": "#d45d5d",
    "Drawing": "#7a6ed2",
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

    parser = argparse.ArgumentParser(description="adalog recording interface")
    parser.add_argument("--session-dir", type=str, default="sessions", help="Directory to save session data")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    set_theme(app)
    window = MainWindow(args.session_dir)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
