"""Entry point: QApplication + main window. Run with `python -m gametrans`.

Loads config.default.json + config.user.json (never crashes on bad
config -- see config.py), sets up logging, then shows the main control
window. Autostart (spec section 3D) is handled by MainWindow itself once
`cfg["autostart"]` is wired up in a later phase; for now the user presses
"เริ่มแปล" manually (matches the MVP scope note in DECISIONS.md phase 5).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6 import QtWidgets

from gametrans.config import load_config
from gametrans.log import setup_logging
from gametrans.ui_main import MainWindow


def main() -> int:
    cfg = load_config(user_path="config.user.json", default_path="config.default.json")
    setup_logging(cfg)

    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow(cfg)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
