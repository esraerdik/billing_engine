"""
user_window.py
---------------
Kullanıcı panelinin TEK ekranı: fatura hesaplama.

Bu pencere hiçbir hesaplama/izin mantığı İÇERMEZ — "Hesapla"
butonuna basıldığında mevcut `UserBillingPanel.run_billing()` metodu
çağrılır (bkz. authorization.py). Bu dosyanın tek işi: tablodan/
kutulardan veri toplamak, `run_billing()`'e Python nesneleri olarak
vermek, dönen `BillingSummary`'yi veya fırlatılan hatayı ekranda
göstermek.
"""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget, QScrollArea,
)

from domain.exceptions import AdminApprovalRequiredError, BillingEngineError
from domain.models import Apartment, BillingPeriod, BillingSummary
from ui.app_context import AppContext
from ui.formatting import TURKISH_MONTH_NAMES

_APARTMENT_COLUMNS = ("Daire No", "Alan (m²)", "Enerji Tüketimi (kW)")
_RESULT_COLUMNS = (
    "Daire No",
    "Sabit Gider (TL)",
    "Tüketim Gideri (TL)",
    "Toplam Ödeme (TL)",
)

# Daire tablosundaki sütun indeksleri — kod içinde sayı yerine isimle
# anılsın diye. Enerji sütunu ayrıca işaretli: bkz. _read_energy_for_row.
_COLUMN_APARTMENT_ID = 0
_COLUMN_AREA = 1
_COLUMN_ENERGY = 2


class UserWindow(QWidget):
    """Kullanıcının fatura hesaplama yaptığı tek ekran."""

    def __init__(self, context: AppContext) -> None:
        super().__init__()
        self._context = context
        self._build_ui()
        self._add_row()  # boş tabloyla başlamasın diye bir satırla açılır

    # ------------------------------------------------------------------
    # Arayüz kurulumu
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.setWindowTitle("Isınma Gider Paylaşımı — Kullanıcı Paneli")
        self.resize(900, 760)

        title_label = QLabel("Fatura Hesaplama")
        title_label.setProperty("role", "heading")
        subtitle_label = QLabel(
            "Dönemi seçin, daire bilgilerini girin ve hesaplayın."
        )
        subtitle_label.setProperty("role", "subheading")

        logout_button = QPushButton("Çıkış Yap")
        logout_button.setObjectName("secondaryButton")
        logout_button.clicked.connect(self._logout)

        header_layout = QHBoxLayout()
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        header_layout.addWidget(logout_button)

        info_group = self._build_info_group()
        apartments_group = self._build_apartments_group()
        calculate_layout = self._build_calculate_button()
        results_group = self._build_results_group()

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(28, 24, 28, 24)
        main_layout.setSpacing(14)
        main_layout.addLayout(header_layout)
        main_layout.addWidget(subtitle_label)
        main_layout.addSpacing(4)
        main_layout.addWidget(info_group)
        main_layout.addWidget(apartments_group, 1)
        main_layout.addLayout(calculate_layout)
        main_layout.addWidget(results_group, 1)
        container = QWidget()
        container.setLayout(main_layout)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(container)

        window_layout = QVBoxLayout()
        window_layout.addWidget(scroll)

        self.setLayout(window_layout)

    def _build_info_group(self) -> QGroupBox:
        info_group = QGroupBox("Dönem ve Fatura Bilgisi")

        current_year = datetime.now().year
        current_year = datetime.now().year

        self._year_combo = QComboBox()

        for year in range(current_year - 10, current_year + 1):
            self._year_combo.addItem(str(year))

        # Varsayılan olarak mevcut yıl seçili gelsin
        self._year_combo.setCurrentText(str(current_year))

        self._year_combo.setEnabled(True)

        self._month_combo = QComboBox()
        self._month_combo.addItems(TURKISH_MONTH_NAMES)
        self._month_combo.setCurrentIndex(datetime.now().month - 1)

        self._total_bill_input = QLineEdit()
        self._total_bill_input.setPlaceholderText("örn. 45000")

        layout = QHBoxLayout()

        layout.addWidget(QLabel("Yıl:"))
        layout.addWidget(self._year_combo)

        layout.addSpacing(15)

        layout.addWidget(QLabel("Ay:"))
        layout.addWidget(self._month_combo)

        layout.addSpacing(28)

        layout.addWidget(QLabel("Toplam Fatura (TL):"))
        layout.addWidget(self._total_bill_input)

        layout.addStretch()
        layout.addStretch()
        info_group.setLayout(layout)
        return info_group

    def _build_apartments_group(self) -> QGroupBox:
        apartments_group = QGroupBox("Daire Bilgileri")

        self._apartment_table = QTableWidget(0, len(_APARTMENT_COLUMNS))
        self._apartment_table.setHorizontalHeaderLabels(list(_APARTMENT_COLUMNS))
        self._apartment_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._apartment_table.verticalHeader().setVisible(False)
        self._apartment_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._apartment_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._apartment_table.setMinimumHeight(200)
        self._apartment_table.verticalHeader().setDefaultSectionSize(50)

        add_row_button = QPushButton("+ Satır Ekle")
        add_row_button.setObjectName("secondaryButton")
        add_row_button.clicked.connect(self._add_row)

        remove_row_button = QPushButton("Satır Sil")
        remove_row_button.setObjectName("dangerButton")
        remove_row_button.clicked.connect(self._remove_selected_row)

        buttons_layout = QHBoxLayout()
        buttons_layout.addWidget(add_row_button)
        buttons_layout.addWidget(remove_row_button)
        buttons_layout.addStretch()

        layout = QVBoxLayout()
        layout.addWidget(self._apartment_table)
        layout.addLayout(buttons_layout)
        apartments_group.setLayout(layout)
        return apartments_group

    def _build_calculate_button(self) -> QHBoxLayout:
        calculate_button = QPushButton("Hesapla")
        calculate_button.setObjectName("primaryButton")
        calculate_button.setMinimumWidth(180)
        calculate_button.clicked.connect(self._handle_calculate)

        layout = QHBoxLayout()
        layout.addStretch()
        layout.addWidget(calculate_button)
        layout.addStretch()
        return layout

    def _build_results_group(self) -> QGroupBox:
        results_group = QGroupBox("Sonuçlar")

        self._result_table = QTableWidget(0, len(_RESULT_COLUMNS))
        self._result_table.setHorizontalHeaderLabels(list(_RESULT_COLUMNS))
        self._result_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._result_table.verticalHeader().setVisible(False)
        self._result_table.setMinimumHeight(180)

        layout = QVBoxLayout()
        layout.addWidget(self._result_table)
        results_group.setLayout(layout)
        return results_group

    # ------------------------------------------------------------------
    # Daire tablosu satır işlemleri
    # ------------------------------------------------------------------

    def _add_row(self) -> None:
        """Daire tablosuna, Daire No'su otomatik önerilen boş bir satır ekler."""
        row = self._apartment_table.rowCount()
        self._apartment_table.insertRow(row)
        self._apartment_table.setItem(
            row, _COLUMN_APARTMENT_ID, QTableWidgetItem(str(row + 1))
        )
        self._apartment_table.setItem(row, _COLUMN_AREA, QTableWidgetItem(""))
        self._apartment_table.setItem(row, _COLUMN_ENERGY, QTableWidgetItem(""))
        self._apartment_table.setCurrentCell(row, _COLUMN_AREA)

    def _remove_selected_row(self) -> None:
        """Tabloda seçili olan satırı siler; seçili satır yoksa uyarır."""
        current_row = self._apartment_table.currentRow()
        if current_row < 0:
            self._show_warning(
                "Satır Seçilmedi", "Silmek için önce bir daire satırı seçin."
            )
            return
        self._apartment_table.removeRow(current_row)

    def _cell_text(self, table: QTableWidget, row: int, column: int) -> str:
        item = table.item(row, column)
        return item.text().strip() if item is not None else ""

    def _read_energy_for_row(self, row: int) -> float:
        """Bu satırdaki dairenin enerji tüketim değerini döndürür.

        ŞİMDİLİK: tablodaki ilgili hücreye kullanıcının manuel yazdığı
        değeri okur (`ValueError` fırlatabilir — çağıran yer bunu
        yakalar).

        İLERİDE (Modbus entegrasyonu): bu metodun İÇİ, aynı imzayı
        (parametre: `row`, dönüş: `float`) koruyarak, kalorimetreden
        Modbus üzerinden okunan değeri önce ilgili hücreye yazıp
        sonra döndürecek şekilde değiştirilebilir. `_handle_calculate`,
        tablo sütun yapısı ve sonucun işlenme şekli hiç değişmeden
        kalır — değişiklik yalnızca bu tek metodun gövdesiyle sınırlı
        olur.
        """
        return float(self._cell_text(self._apartment_table, row, _COLUMN_ENERGY))

    # ------------------------------------------------------------------
    # Hesapla akışı
    # ------------------------------------------------------------------

    def _handle_calculate(self) -> None:
        """"Hesapla" butonuna basıldığında çalışır.

        Akış: girdileri topla/ayrıştır → `UserBillingPanel.run_billing()`
        çağır → sonucu göster ya da hatayı `QMessageBox` ile bildir.
        Hesaplama/izin mantığının KENDİSİ burada YOKTUR; hepsi
        `run_billing()` içinde — bu metod yalnızca girdi/çıktı köprüsü.
        """
        total_bill = self._parse_total_bill()
        if total_bill is None:
            return

        apartments = self._read_apartments_from_table()
        if apartments is None:
            return

        month = self._month_combo.currentIndex() + 1  # 0-tabanlı -> 1-12
        year = datetime.now().year
        period = BillingPeriod(year=year, month=month)

        try:
            summary = self._context.user_panel.run_billing(
                period, total_bill, apartments
            )
        except AdminApprovalRequiredError as error:
            self._show_warning("Admin Onayı Gerekli", str(error))
            return
        except BillingEngineError as error:
            self._show_error("Hesaplama Hatası", str(error))
            return

        self._populate_results(summary)

    def _parse_total_bill(self) -> float | None:
        """Fatura tutarı kutusundaki metni `float`'a çevirir.

        Negatif değer kontrolü burada YAPILMAZ — o `BillingCalculator`ın
        sorumluluğu (`NegativeBillError`). Bu metod sadece "bu bir
        sayı mı" sorusuna cevap verir.
        """
        raw_text = self._total_bill_input.text().strip()
        try:
            return float(raw_text)
        except ValueError:
            self._show_error(
                "Geçersiz Tutar", f"'{raw_text}' geçerli bir sayı değil."
            )
            return None

    def _read_apartments_from_table(self) -> list[Apartment] | None:
        """Daire tablosundaki tüm satırları `Apartment` nesnelerine çevirir.

        Bir satırda geçersiz (sayı olmayan) veri varsa `None` döner ve
        kullanıcıyı hangi satırda sorun olduğu konusunda bilgilendirir;
        bu durumda `run_billing()` hiç ÇAĞRILMAZ. Tablo boşsa (hiç
        satır yoksa), burada özel bir kontrol YAPILMAZ — boş liste
        olduğu gibi `run_billing()`'e gider ve mevcut
        `EmptyApartmentListError` doğal olarak devreye girer; aynı
        kuralın iki yerde ayrı ayrı yazılmasını istemiyoruz.
        """
        apartments: list[Apartment] = []
        row_count = self._apartment_table.rowCount()
        for row in range(row_count):
            try:
                apartment_id = int(
                    self._cell_text(self._apartment_table, row, _COLUMN_APARTMENT_ID)
                )
                area = float(
                    self._cell_text(self._apartment_table, row, _COLUMN_AREA)
                )
                energy = self._read_energy_for_row(row)
            except ValueError:
                self._show_error(
                    "Geçersiz Daire Verisi",
                    f"{row + 1}. satırdaki değerler sayısal olmalı. "
                    "Lütfen kontrol edin.",
                )
                return None
            apartments.append(Apartment(id=apartment_id, area=area, energy=energy))
        return apartments

    def _populate_results(self, summary: BillingSummary) -> None:
        """Hesaplama sonucunu, sonuç tablosunda gösterir.

        Gösterilen değerler `.rounded()` ile alınır — iç hesaplamalar
        (kontrol toplamı gibi) hep tam hassasiyetle kalır, yuvarlama
        yalnızca burada, sunum aşamasında uygulanır (bkz. models.py).
        """
        self._result_table.setRowCount(0)
        for result in summary.results:
            rounded = result.rounded()
            row = self._result_table.rowCount()
            self._result_table.insertRow(row)
            values = (
                str(rounded.apartment_id),
                f"{rounded.fixed_share:,.2f}",
                f"{rounded.consumption_share:,.2f}",
                f"{rounded.total_payable:,.2f}",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                # Sonuç hücreleri hesaplanmış veridir; kullanıcı
                # yanlışlıkla değiştirmesin diye salt-okunur yapılır.
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._result_table.setItem(row, column, item)

    # ------------------------------------------------------------------
    # Mesaj kutuları (test edilebilirlik için ayrı metodlar)
    # ------------------------------------------------------------------

    def _show_error(self, title: str, message: str) -> None:
        QMessageBox.critical(self, title, message)

    def _show_warning(self, title: str, message: str) -> None:
        QMessageBox.warning(self, title, message)

    def _logout(self):
        from ui.login_window import LoginWindow

        self._login_window = LoginWindow(self._context)
        self._login_window.show()

        self.close()
