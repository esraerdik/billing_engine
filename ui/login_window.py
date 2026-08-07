"""
login_window.py
----------------
Uygulama açıldığında ilk gösterilen Giriş ekranı.

Kullanıcı adı/şifreyi `auth.authenticate()` ile doğrular (bkz.
auth.py — bu geçici, sabit kodlu bir kontroldür) ve role göre
`UserWindow` veya `AdminWindow`'u açar. Bu pencere kendisi hiçbir
iş mantığı içermez; sadece yönlendirme yapar.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui.app_context import AppContext
from ui.auth import UserRole, authenticate


class LoginWindow(QWidget):
    """Kullanıcı adı/şifre alıp role göre ilgili paneli açan giriş ekranı."""

    def __init__(self, context: AppContext) -> None:
        super().__init__()
        self._context = context
        # Açılan User/Admin penceresine referansı burada tutuyoruz —
        # tutulmazsa Python nesneyi çöp toplayabilir ve pencere hemen
        # kapanır (PyQt'te sık karşılaşılan bir tuzak).
        self._opened_window: QWidget | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        self.setWindowTitle("Isınma Gider Paylaşımı — Giriş")
        self.setFixedSize(360, 320)

        title_label = QLabel("Isınma Gider Paylaşımı")
        title_label.setProperty("role", "heading")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        subtitle_label = QLabel("Devam etmek için giriş yapın")
        subtitle_label.setProperty("role", "subheading")
        subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        username_label = QLabel("Kullanıcı Adı")
        self._username_input = QLineEdit()
        self._username_input.setPlaceholderText("kullanıcı adınızı girin")
        self._username_input.setMinimumHeight(40)

        password_label = QLabel("Şifre")
        self._password_input = QLineEdit()
        self._password_input.setPlaceholderText("şifrenizi girin")
        self._password_input.setMinimumHeight(40)
        self._password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._password_input.returnPressed.connect(self._handle_login)

        login_button = QPushButton("Giriş Yap")
        login_button.setObjectName("primaryButton")
        login_button.setFixedHeight(45)
        login_button.clicked.connect(self._handle_login)


        layout = QVBoxLayout()
        layout.setContentsMargins(36, 32, 36, 32)
        layout.setSpacing(6)
        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)
        layout.addSpacing(20)
        layout.addWidget(username_label)
        layout.addWidget(self._username_input)
        layout.addSpacing(10)
        layout.addWidget(password_label)
        layout.addWidget(self._password_input)
        layout.addSpacing(22)
        layout.addWidget(login_button)
        layout.addStretch()
        self.setLayout(layout)

        self._username_input.setFocus()

    def _handle_login(self) -> None:
        """Girilen bilgileri doğrular; başarılıysa role göre pencere açar."""
        username = self._username_input.text().strip()
        password = self._password_input.text()

        role = authenticate(username, password)
        if role is None:
            self._show_login_error(
                "Giriş Başarısız", "Kullanıcı adı veya şifre hatalı."
            )
            self._password_input.clear()
            self._password_input.setFocus()
            return

        self._opened_window = self._build_window_for_role(role)
        self._opened_window.show()
        self.close()

    def _show_login_error(self, title: str, message: str) -> None:
        """Ayrı bir metod olarak tutulur — user_window.py/admin_window.py'deki
        `_show_error` deseniyle tutarlı: testlerde bu metod monkeypatch
        edilerek gerçek bir modal diyalog açılmadan giriş hatası akışı
        doğrulanabilir.
        """
        QMessageBox.warning(self, title, message)

    def _build_window_for_role(self, role: UserRole) -> QWidget:
        """Role göre ilgili panel penceresini oluşturur.

        İçe aktarmalar burada, fonksiyonun İÇİNDE yapılıyor (modül
        seviyesinde değil) — `user_window.py` ve `admin_window.py`,
        `login_window.py`'yi import etmez; ama tersi bir döngüsel
        bağımlılığı da baştan engellemiş oluyoruz, çünkü hiçbiri
        gerçekte birbirini import etmiyor.
        """
        if role is UserRole.ADMIN:
            from ui.admin_window import AdminWindow

            return AdminWindow(self._context)

        from ui.user_window import UserWindow

        return UserWindow(self._context)
