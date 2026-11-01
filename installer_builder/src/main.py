"""Start the graphical installer."""

import argparse
import logging
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from src.gui.main_window import MainWindow
else:
    from .gui.main_window import MainWindow

from PySide6.QtWidgets import QApplication


def main() -> int:
    parser = argparse.ArgumentParser(description="Simple Windows Installer")
    parser.add_argument("package", nargs="?", type=Path, help="Optionales .installer-Paket")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = QApplication([sys.argv[0]])
    window = MainWindow(args.package)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
