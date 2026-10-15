"""Ponto de entrada do J.A.R.V.I.S."""
import os
import sys
import tempfile

if sys.stdout is None or sys.stderr is None:
    _log = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "jarvis.log"),
                "a", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = _log
    if sys.stderr is None:
        sys.stderr = _log

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QLockFile

import ferramentas
from jarvis.controller import JarvisController


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setQuitOnLastWindowClosed(False)

    lock = QLockFile(os.path.join(tempfile.gettempdir(), "jarvis.lock"))
    if not lock.tryLock(100):
        print("JARVIS já está em execução.")
        return 0

    try:
        print(ferramentas.backup_codigo(None))
    except Exception as exc:
        print(f"[backup] falhou: {exc}")

    controller = JarvisController()
    app.aboutToQuit.connect(controller.shutdown)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
