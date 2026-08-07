"""
styles.py (invoice_pdf)
-------------------------
Renk paleti, yazı tipi kaydı ve ReportLab paragraf/tablo stilleri.

Font kaydı (`register_fonts`) bir yedekleme (fallback) zinciri izler:
    1. Bu paketle birlikte gelen `invoice_pdf/fonts/DejaVuSans*.ttf`
       (Unicode, Türkçe karakterleri — ı, İ, ğ, ş, ö, ü, ç — tam destekler,
       serbestçe dağıtılabilir Bitstream Vera lisanslıdır).
    2. Bulunamazsa, yaygın Windows sistem fontları (yalnızca yerel
       geliştirme ortamı için bir kolaylık; dağıtılmaz, sadece dosya
       yolundan referans alınır).
    3. O da yoksa ReportLab'in yerleşik Helvetica'sına sessizce düşülür
       (bu durumda dotless-ı/İ gibi bazı Türkçe karakterler tam doğru
       render edilmeyebilir — bir uyarı loglanır).

Bu modül Django'dan HABERSİZDİR; sadece ReportLab'e bağımlıdır.
"""

from __future__ import annotations

import logging
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

logger = logging.getLogger(__name__)

# Kurumsal renk paleti — mavi (başlıklar/vurgular) ve yeşil (olumlu/toplam
# vurgusu) ana temayı oluşturur; mevcut web panelindeki mavi (#2563eb) ile
# tutarlıdır (bkz. static/css/dashboard.css).
COLOR_PRIMARY_BLUE = colors.HexColor("#2563eb")
COLOR_DARK_BLUE = colors.HexColor("#1e3a8a")
COLOR_ACCENT_GREEN = colors.HexColor("#16a34a")
COLOR_LIGHT_BLUE_BG = colors.HexColor("#eff6ff")
COLOR_LIGHT_GREEN_BG = colors.HexColor("#f0fdf4")
COLOR_TABLE_GRID = colors.HexColor("#d9d9d9")
COLOR_TEXT_DARK = colors.HexColor("#1f2937")
COLOR_TEXT_MUTED = colors.HexColor("#6b7280")
COLOR_WHITE = colors.white

_FONTS_DIR = Path(__file__).resolve().parent / "fonts"

# Yalnızca yerel Windows geliştirme ortamında bulunması muhtemel, Türkçe
# karakterleri destekleyen sistem fontları — dosyalar PROJEYE KOPYALANMAZ,
# sadece varsa mutlak yoldan kayıt edilir.
_WINDOWS_FALLBACK_FONTS = [
    (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\arialbd.ttf"),
    (r"C:\Windows\Fonts\calibri.ttf", r"C:\Windows\Fonts\calibrib.ttf"),
    (r"C:\Windows\Fonts\tahoma.ttf", r"C:\Windows\Fonts\tahomabd.ttf"),
]

_registered_font_name: str | None = None
_registered_bold_font_name: str | None = None


def register_fonts() -> tuple[str, str]:
    """Türkçe karakter destekli bir font kaydeder ve (normal, kalın) isim
    çiftini döndürür.

    Sonuç modül seviyesinde önbelleğe alınır — aynı süreç içinde birden
    fazla PDF üretilse bile font kaydı yalnızca bir kez yapılır (ReportLab
    aynı ismi tekrar kaydetmeye izin verir ama gereksizdir).
    """
    global _registered_font_name, _registered_bold_font_name

    if _registered_font_name is not None and _registered_bold_font_name is not None:
        return _registered_font_name, _registered_bold_font_name

    bundled_regular = _FONTS_DIR / "DejaVuSans.ttf"
    bundled_bold = _FONTS_DIR / "DejaVuSans-Bold.ttf"

    if bundled_regular.exists() and bundled_bold.exists():
        pdfmetrics.registerFont(TTFont("Invoice-Regular", str(bundled_regular)))
        pdfmetrics.registerFont(TTFont("Invoice-Bold", str(bundled_bold)))
        _registered_font_name = "Invoice-Regular"
        _registered_bold_font_name = "Invoice-Bold"
        return _registered_font_name, _registered_bold_font_name

    for regular_path, bold_path in _WINDOWS_FALLBACK_FONTS:
        if Path(regular_path).exists() and Path(bold_path).exists():
            pdfmetrics.registerFont(TTFont("Invoice-Regular", regular_path))
            pdfmetrics.registerFont(TTFont("Invoice-Bold", bold_path))
            _registered_font_name = "Invoice-Regular"
            _registered_bold_font_name = "Invoice-Bold"
            return _registered_font_name, _registered_bold_font_name

    logger.warning(
        "invoice_pdf: Unicode TTF bulunamadı, Helvetica'ya düşülüyor — "
        "bazı Türkçe karakterler (ı, İ, ğ) tam doğru görünmeyebilir."
    )
    _registered_font_name = "Helvetica"
    _registered_bold_font_name = "Helvetica-Bold"
    return _registered_font_name, _registered_bold_font_name


def get_paragraph_styles() -> dict[str, ParagraphStyle]:
    """PDF boyunca kullanılan tüm `ParagraphStyle`ları döndürür."""
    regular_font, bold_font = register_fonts()

    return {
        "system_title": ParagraphStyle(
            "system_title",
            fontName=bold_font,
            fontSize=16,
            leading=20,
            textColor=COLOR_DARK_BLUE,
            alignment=TA_LEFT,
        ),
        "header_date": ParagraphStyle(
            "header_date",
            fontName=regular_font,
            fontSize=9.5,
            leading=13,
            textColor=COLOR_TEXT_MUTED,
            alignment=TA_RIGHT,
        ),
        "complex_name": ParagraphStyle(
            "complex_name",
            fontName=bold_font,
            fontSize=12,
            leading=15,
            textColor=COLOR_PRIMARY_BLUE,
            alignment=TA_CENTER,
        ),
        "document_title": ParagraphStyle(
            "document_title",
            fontName=bold_font,
            fontSize=13,
            leading=17,
            textColor=COLOR_WHITE,
            alignment=TA_CENTER,
        ),
        "section_header": ParagraphStyle(
            "section_header",
            fontName=bold_font,
            fontSize=11,
            leading=14,
            textColor=COLOR_WHITE,
        ),
        "label": ParagraphStyle(
            "label",
            fontName=regular_font,
            fontSize=9.5,
            leading=13,
            textColor=COLOR_TEXT_MUTED,
        ),
        "value": ParagraphStyle(
            "value",
            fontName=bold_font,
            fontSize=9.5,
            leading=13,
            textColor=COLOR_TEXT_DARK,
        ),
        "table_header": ParagraphStyle(
            "table_header",
            fontName=bold_font,
            fontSize=9.5,
            leading=12,
            textColor=COLOR_WHITE,
            alignment=TA_CENTER,
        ),
        "table_cell": ParagraphStyle(
            "table_cell",
            fontName=regular_font,
            fontSize=9.5,
            leading=12,
            textColor=COLOR_TEXT_DARK,
            alignment=TA_LEFT,
        ),
        "table_cell_right": ParagraphStyle(
            "table_cell_right",
            fontName=regular_font,
            fontSize=9.5,
            leading=12,
            textColor=COLOR_TEXT_DARK,
            alignment=TA_RIGHT,
        ),
        "table_cell_total": ParagraphStyle(
            "table_cell_total",
            fontName=bold_font,
            fontSize=10.5,
            leading=13,
            textColor=COLOR_ACCENT_GREEN,
            alignment=TA_RIGHT,
        ),
        "footer": ParagraphStyle(
            "footer",
            fontName=regular_font,
            fontSize=7.5,
            leading=10,
            textColor=COLOR_TEXT_MUTED,
            alignment=TA_CENTER,
        ),
    }
