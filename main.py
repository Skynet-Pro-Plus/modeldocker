import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from ui_main import ModelDockerMainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("ModelDocker")
    # Explicit pt size avoids QFont::setPointSize (-1) warnings when stylesheets
    # leave fonts "unset" (pointSize == -1) on Windows / HiDPI.
    base = QFont()
    base.setFamilies(["Segoe UI", "Inter", "Arial"])
    base.setPointSize(10)
    app.setFont(base)
    window = ModelDockerMainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
