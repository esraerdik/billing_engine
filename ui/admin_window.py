"""
admin_window.py
----------------
Admin panelinin TEK ekranı: onay bekleyen taleplerin listesi.

Bu pencere hiçbir izin mantığı İÇERMEZ — "Onayla"/"Reddet"
butonlarına basıldığında mevcut `AdminBillingPanel.approve()` /
`AdminBillingPanel.deny()` metodları çağrılır (bkz. authorization.py).

ÖNEMLİ İSİMLENDİRME NOTU: Görev tanımında "Reddet butonu mevcut
reject() metodunu kullansın" deniyor; ancak `AdminBillingPanel`
sınıfında böyle bir metod YOK — karşılığı `deny()`. Business logic
sınıflarına dokunulmaması istendiği için burada `reject()` diye yeni
bir metod EKLEMEDİM; mevcut `deny()` doğrudan kullanılıyor.
"""

from __future__ import annotations

from functools import partial

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from domain.models import BillingPeriod
from ui.app_context import AppContext
from ui.formatting import format_period

_COLUMN_PERIOD = 0
_COLUMN_APPROVE = 1
_COLUMN_REJECT = 2
_COLUMN_HEADERS = ("Ay", "Onayla", "Reddet")


class AdminWindow(QWidget):
    """Onay bekleyen talepleri listeleyip onaylama/reddetme imkânı veren tek ekran."""

    def __init__(self, context: AppContext) -> None:
        super().__init__()
        self._context = context
        self._build_ui()
        self._load_pending_requests()

    # ------------------------------------------------------------------
    # Arayüz kurulumu
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.setWindowTitle("Isınma Gider Paylaşımı — Admin Paneli")
        self.resize(680, 520)

        title_label = QLabel("Onay Bekleyen Talepler")
        title_label.setProperty("role", "heading")

        refresh_button = QPushButton("Yenile")
        refresh_button.setObjectName("secondaryButton")
        refresh_button.clicked.connect(self._load_pending_requests)

        logout_button = QPushButton("Çıkış Yap")
        logout_button.setObjectName("secondaryButton")
        logout_button.clicked.connect(self._logout)

        header_layout = QHBoxLayout()
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        header_layout.addWidget(refresh_button)
        header_layout.addWidget(logout_button)

        subtitle_label = QLabel(
            "Aylık hakkı dolmuş ve tekrar çalıştırma bekleyen dönemler."
        )
        subtitle_label.setProperty("role", "subheading")

        self._table = QTableWidget(0, len(_COLUMN_HEADERS))
        self._table.setHorizontalHeaderLabels(list(_COLUMN_HEADERS))
        header = self._table.horizontalHeader()

        header.setSectionResizeMode(_COLUMN_PERIOD, QHeaderView.ResizeMode.Stretch)

        header.setSectionResizeMode(_COLUMN_APPROVE, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(_COLUMN_REJECT, QHeaderView.ResizeMode.Fixed)

        self._table.setColumnWidth(_COLUMN_APPROVE, 140)
        self._table.setColumnWidth(_COLUMN_REJECT, 140)

        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._table.setMinimumHeight(220)
        self._table.verticalHeader().setDefaultSectionSize(50)

        self._empty_label = QLabel("Şu anda onay bekleyen bir talep yok.")
        self._empty_label.setProperty("role", "subheading")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(28, 24, 28, 24)
        main_layout.setSpacing(14)
        main_layout.addLayout(header_layout)
        main_layout.addWidget(subtitle_label)
        main_layout.addSpacing(6)
        main_layout.addWidget(self._table, 1)
        main_layout.addWidget(self._empty_label)
        self.setLayout(main_layout)

    # ------------------------------------------------------------------
    # Liste yükleme
    # ------------------------------------------------------------------

    def _load_pending_requests(self) -> None:
        """Bekleyen talep listesini `AdminBillingPanel.pending_periods()`'tan yeniden okur.

        Bu ekranda otomatik/canlı bildirim YOKTUR (örn. kullanıcı
        panelinde yeni bir talep oluştuğunda admin ekranı kendiliğinden
        güncellenmez) — bu yüzden "Yenile" butonu var; pencere ilk
        açıldığında da bir kez otomatik çağrılır.
        """
        pending_periods = self._context.admin_panel.pending_periods()

        self._table.setRowCount(0)
        for period in pending_periods:
            self._add_pending_row(period)

        has_pending = len(pending_periods) > 0
        self._table.setVisible(has_pending)
        self._empty_label.setVisible(not has_pending)

    def _add_pending_row(self, period: BillingPeriod) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)

        period_item = QTableWidgetItem(format_period(period))
        period_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        period_item.setFlags(period_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, _COLUMN_PERIOD, period_item)

        approve_button = QPushButton("Onayla")
        approve_button.setObjectName("approveButton")
        # functools.partial ile `period` her satır için AYRI yakalanır;
        # döngü değişkenini doğrudan lambda'ya kapatmak (closure) klasik
        # bir tuzaktır — tüm butonlar son satırın period'unu paylaşırdı.
        approve_button.setFixedSize(110, 40)
        approve_button.clicked.connect(partial(self._handle_approve, period))
        self._table.setCellWidget(row, _COLUMN_APPROVE, approve_button)

        reject_button = QPushButton("Reddet")
        reject_button.setObjectName("rejectButton")
        reject_button.setFixedSize(110, 40)
        reject_button.clicked.connect(partial(self._handle_reject, period))
        self._table.setCellWidget(row, _COLUMN_REJECT, reject_button)

    # ------------------------------------------------------------------
    # Onayla / Reddet
    # ------------------------------------------------------------------

    def _handle_approve(self, period: BillingPeriod) -> None:
        """Mevcut `AdminBillingPanel.approve()` metodunu çağırır."""
        self._context.admin_panel.approve(period)
        self._load_pending_requests()

    def _handle_reject(self, period: BillingPeriod) -> None:
        """Mevcut `AdminBillingPanel.deny()` metodunu çağırır.

        (Görev tanımındaki `reject()` adı yerine — bkz. dosya başındaki not.)
        """
        self._context.admin_panel.deny(period)
        self._load_pending_requests()

    def _logout(self):
        from ui.login_window import LoginWindow

        self._login_window = LoginWindow(self._context)
        self._login_window.show()

        self.close()
