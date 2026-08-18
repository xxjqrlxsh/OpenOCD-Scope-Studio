from __future__ import annotations

import os
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from .ui import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("OpenOCD Scope")
    window = MainWindow()
    window.show()
    if os.environ.get("OPENOCD_SCOPE_SMOKE_TEST") == "1":
        QTimer.singleShot(1500, app.quit)
    return app.exec()
