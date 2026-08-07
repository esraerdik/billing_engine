"""
theme.py
--------
Uygulama genelinde kullanılan tek bir QSS stil sayfası.

Renk/tipografi kararları burada TEK YERDE toplanır; her pencere kendi
stilini tekrar tanımlasaydı, ileride bir renk değişikliğinde üç
dosyayı ayrı ayrı güncellemek gerekirdi. `gui_main.py`, bu sayfayı
`QApplication` seviyesinde bir kez uygular; tüm pencereler otomatik
olarak aynı görünümü miras alır.

Tasarım kararları:
    - Açık, soğuk gri zemin (#F6F7F9) üzerinde beyaz "kart" yüzeyler
      (QGroupBox, QTableWidget) — ince kenarlık ve yuvarlatılmış
      köşelerle ayrışır.
    - Vurgu rengi jenerik bir "Bootstrap mavisi" değil, ölçülü bir
      çam yeşili (#0F6E5C): onay/pozitif işlemler (Hesapla, Onayla)
      için kullanılır, bir finans/idari araç için fazla iddialı
      olmadan güven hissi verir.
    - Reddetme/silme gibi geri alınamaz işlemler (Reddet, Satır Sil)
      yumuşak bir kiremit kırmızısı ile işaretlenir — alarm kırmızısı
      kadar sert değil, ama "dikkatli ol" sinyalini veriyor.
    - Yazı tipi olarak platformlarda güvenilir şekilde bulunan bir
      sistem fontu ailesi kullanılır (web'in aksine, masaüstünde özel
      bir font dosyası gömmeden farklı bir görünüm sağlamak pratik
      değil — kullanıcının makinesinde kurulu olmayan bir font sessizce
      bir sistem fontuna düşer ve tutarsız görünür).
"""

from __future__ import annotations

# --- Renk paleti (tek kaynak) ---------------------------------------------
BACKGROUND = "#F6F7F9"
SURFACE = "#FFFFFF"
BORDER = "#E2E5EA"
TEXT_PRIMARY = "#1F2A37"
TEXT_SECONDARY = "#6B7280"
ACCENT = "#0F6E5C"
ACCENT_HOVER = "#0C5C4D"
ACCENT_PRESSED = "#0A4C40"
ACCENT_SOFT = "#E6F2EF"
DANGER = "#B3261E"
DANGER_SOFT = "#FDEDEC"
DANGER_SOFT_BORDER = "#F3CFC9"
DANGER_SOFT_HOVER = "#F9DAD6"
NEUTRAL_BUTTON = "#F1F2F4"
NEUTRAL_BUTTON_BORDER = "#D7DAE0"
NEUTRAL_BUTTON_HOVER = "#E7E9EC"

FONT_FAMILY = '"Segoe UI", "Helvetica Neue", Arial, sans-serif'

APP_STYLESHEET = f"""
QWidget {{
    background-color: {BACKGROUND};
    color: {TEXT_PRIMARY};
    font-family: {FONT_FAMILY};
    font-size: 10.5pt;
}}

QLabel[role="heading"] {{
    font-size: 15pt;
    font-weight: 600;
    color: {TEXT_PRIMARY};
}}
QLabel[role="subheading"] {{
    font-size: 10pt;
    color: {TEXT_SECONDARY};
}}
QLabel[role="section-error"] {{
    color: {DANGER};
    font-weight: 600;
}}

QGroupBox {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
    margin-top: 16px;
    padding: 18px 14px 14px 14px;
    font-weight: 600;
    font-size: 11pt;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    padding: 0 6px;
    color: {ACCENT};
}}

QLineEdit, QComboBox {{
    background-color: {SURFACE};
    border: 1px solid {NEUTRAL_BUTTON_BORDER};
    border-radius: 6px;
    padding: 7px 10px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QComboBox:focus {{
    border: 1.5px solid {ACCENT};
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}

QPushButton {{
    border-radius: 6px;
    padding: 9px 18px;
    font-weight: 600;
    border: 1px solid transparent;
}}
QPushButton#primaryButton {{
    background-color: {ACCENT};
    color: #FFFFFF;
}}
QPushButton#primaryButton:hover {{
    background-color: {ACCENT_HOVER};
}}
QPushButton#primaryButton:pressed {{
    background-color: {ACCENT_PRESSED};
}}
QPushButton#secondaryButton {{
    background-color: {NEUTRAL_BUTTON};
    color: {TEXT_PRIMARY};
    border: 1px solid {NEUTRAL_BUTTON_BORDER};
}}
QPushButton#secondaryButton:hover {{
    background-color: {NEUTRAL_BUTTON_HOVER};
}}
QPushButton#dangerButton {{
    background-color: {DANGER_SOFT};
    color: {DANGER};
    border: 1px solid {DANGER_SOFT_BORDER};
}}
QPushButton#dangerButton:hover {{
    background-color: {DANGER_SOFT_HOVER};
}}
QPushButton#approveButton {{
    background-color: {ACCENT};
    color: #FFFFFF;
    padding: 5px 14px;
    font-size: 9.5pt;
}}
QPushButton#approveButton:hover {{
    background-color: {ACCENT_HOVER};
}}
QPushButton#rejectButton {{
    background-color: {DANGER_SOFT};
    color: {DANGER};
    border: 1px solid {DANGER_SOFT_BORDER};
    padding: 5px 14px;
    font-size: 9.5pt;
}}
QPushButton#rejectButton:hover {{
    background-color: {DANGER_SOFT_HOVER};
}}

QTableWidget {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    gridline-color: #EEF0F3;
    selection-background-color: {ACCENT_SOFT};
    selection-color: {TEXT_PRIMARY};
}}
QHeaderView::section {{
    background-color: {BACKGROUND};
    color: {TEXT_SECONDARY};
    padding: 8px;
    border: none;
    border-bottom: 1px solid {BORDER};
    font-weight: 600;
}}
QTableWidget::item {{
    padding: 6px;
}}
QTableWidget::item:selected {{
    background-color: {ACCENT_SOFT};
    color: {TEXT_PRIMARY};
}}

QMessageBox {{
    background-color: {SURFACE};
}}

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
}}
QScrollBar::handle:vertical {{
    background: {NEUTRAL_BUTTON_BORDER};
    border-radius: 5px;
    min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
"""
