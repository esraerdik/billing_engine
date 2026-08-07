"""
gui_main.py
-----------
PyQt6 arayüzünün başlatma noktası.

Çalıştırmak için proje kök dizininden:

    python -m billing_engine.ui.gui_main

Bu dosya `main.py`'nin YERİNE geçmez — `main.py` hâlâ terminalde
çalışan, kullanıcıdan `input()` ile fatura alan CLI örneğidir ve
olduğu gibi duruyor. Bu dosya, aynı iş mantığına (`AppContext`
üzerinden) bağlanan AYRI, yeni bir giriş noktasıdır.
"""

from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from ui.app_context import build_app_context
from ui.login_window import LoginWindow
from ui.theme import APP_STYLESHEET


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyleSheet(APP_STYLESHEET)

    context = build_app_context()
    login_window = LoginWindow(context)
    login_window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
