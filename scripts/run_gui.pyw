"""No-console launcher for a desktop shortcut: run with pythonw.exe (not
python.exe) so no terminal window flashes open, since app.py is a PySide6
GUI app with its own window. Resolves the project root from this file's
own location so a shortcut can target it from anywhere, then chdir's
there so the app's relative paths (config.default.json, profiles/,
models/, ...) resolve the same way they do via scripts/run.ps1.
"""
import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / "src"))
os.chdir(root)

from gametrans.app import main

if __name__ == "__main__":
    sys.exit(main())
