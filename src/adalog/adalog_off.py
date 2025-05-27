"""
adalog_off.py ─ Offline explorer for Adalog datasets
────────────────────────────────────────────────────
• Always opens with one Inspector dock (stats / overlap matrix).
• Lets you add any extra *offline* panels living in
  adalog/modalities/off/*.py   (class name = CamelCase of the filename).
Run:
    python adalog_off.py --sessions-dir ./sessions
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Dict, Type

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QMainWindow,
    QWidget,
)

# ────────────────────────────────────────────────────────────────
# 1 ─ Theme helper
# ────────────────────────────────────────────────────────────────
def set_dark(app: QApplication) -> None:
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(30, 30, 30))
    pal.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
    pal.setColor(QPalette.ColorRole.Base, QColor(45, 45, 45))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(60, 60, 60))
    pal.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
    app.setPalette(pal)

    app.setStyleSheet("""
        QLabel { color:#fff; font-size:16px; }
        QLineEdit, QPushButton, QComboBox {
            font-size:16px; color:#fff; background:#3d3d3d;
            border:1px solid #555; padding:2px 4px;
        }
    """)

# ────────────────────────────────────────────────────────────────
# 2 ─ Main window
# ────────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self, sessions_root: Path):
        super().__init__()
        self.sessions_root = sessions_root
        self.setWindowTitle("Adalog – Offline Explorer")
        self.resize(1200, 720)

        # Discover all modalities (including Inspector)
        self.off_modalities: Dict[str, Type[QWidget]] = self._discover_off_modalities()

        # # Preload Inspector if present
        # inspector_cls = self.off_modalities.pop("Inspector", None)
        # if inspector_cls:
        #     self._add_dock(inspector_cls(), "Inspector")

        # Top bar UI
        bar = QWidget()
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(6, 4, 6, 4)
        self.combo = QComboBox()
        self.combo.addItems(sorted(self.off_modalities.keys()))
        add_btn = QPushButton("Add panel", clicked=self._spawn_selected)
        lay.addWidget(QLabel("Panel:"))
        lay.addWidget(self.combo)
        lay.addWidget(add_btn)
        lay.addStretch()
        self.setMenuWidget(bar)

    def _discover_off_modalities(self) -> Dict[str, Type[QWidget]]:
        """
        Import every .py in adalog/modalities/off/ and return
        {ClassName: class}, where ClassName is CamelCase of filename.
        """
        import adalog.modalities  # fix here
        modalities_dir = Path(adalog.modalities.__file__).parent
        off_dir = modalities_dir / "off"

        found: Dict[str, Type[QWidget]] = {}
        sys.path.insert(0, str(modalities_dir.parent))  # ensure adalog package root is importable

        for py in off_dir.glob("*.py"):
            if py.stem == "__init__":
                continue
            mod_name = f"adalog.modalities.off.{py.stem}"
            try:
                module = importlib.import_module(mod_name)
                class_name = "".join(part.title() for part in py.stem.split("_"))
                cls = getattr(module, class_name, None)
                if cls:
                    found[class_name] = cls
            except Exception as e:
                print(f"[off] failed to load {mod_name}: {e}", file=sys.stderr)

        return found

    def _spawn_selected(self) -> None:
        name = self.combo.currentText()
        cls = self.off_modalities.get(name)
        if cls:
            self._add_dock(cls(), name)

    def _add_dock(self, widget: QWidget, title: str) -> None:
        dock = QDockWidget(title, self)
        dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        dock.setWidget(widget)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)

# ────────────────────────────────────────────────────────────────
# 3 ─ Entrypoint
# ────────────────────────────────────────────────────────────────
def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--sessions-dir", default="../../sessions", help="Root folder with user sessions")
    args = p.parse_args()

    root = Path(args.sessions_dir).expanduser()
    if not root.exists():
        print(f"[warning] sessions dir '{root}' not found.", file=sys.stderr)

    app = QApplication(sys.argv)
    set_dark(app)
    win = MainWindow(root)
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
