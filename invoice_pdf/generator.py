"""
generator.py (invoice_pdf)
-----------------------------
ReportLab (Platypus) kullanarak `InvoiceData`'dan A4 boyutunda bir PDF
Gider Bildirimi üretir.

Bu modül Django/ORM'den TAMAMEN HABERSİZDİR — girdisi yalnızca
`invoice_pdf.models.InvoiceData` (saf bir dataclass); hiçbir veritabanı
sorgusu, hiçbir iş kuralı/hesaplama İÇERMEZ. Girdi olarak verilen değerleri
olduğu gibi görselleştirir ("PDF kendi hesaplama yapmaz").
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .formatters import (
    format_area,
    format_currency,
    format_date_range_tr,
    format_date_tr,
    format_energy,
    format_optional_energy,
    format_optional_text,
)
from .models import InvoiceData
from .styles import (
    COLOR_ACCENT_GREEN,
    COLOR_LIGHT_BLUE_BG,
    COLOR_LIGHT_GREEN_BG,
    COLOR_PRIMARY_BLUE,
    COLOR_TABLE_GRID,
    COLOR_TEXT_MUTED,
    get_paragraph_styles,
    register_fonts,
)

_PAGE_MARGIN = 18 * mm
_FOOTER_TEXT = (
    "Bu belge, Merkezî Isıtma ve Sıhhî Sıcak Su Sistemlerinde Isınma ve Sıhhî "
    "Sıcak Su Giderlerinin Paylaştırılmasına İlişkin Yönetmelik hükümlerine göre "
    "otomatik olarak oluşturulmuştur."
)


def _make_numbered_canvas(footer_text: str) -> type[pdfcanvas.Canvas]:
    """Her sayfaya "Sayfa X / Y" ve kısa bir bilgilendirme metni ekleyen bir
    `Canvas` alt sınıfı üretir.

    Toplam sayfa sayısı (Y), tüm sayfalar üretilmeden bilinemediği için
    standart ReportLab deseni izlenir: `showPage()` çağrıları hemen
    yazdırılmaz, sayfa durumları biriktirilir; gerçek yazım `save()`
    içinde, toplam sayfa sayısı belli olduktan SONRA yapılır.
    """

    regular_font, _ = register_fonts()

    class NumberedCanvas(pdfcanvas.Canvas):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self._saved_page_states: list[dict] = []

        def showPage(self) -> None:
            self._saved_page_states.append(dict(self.__dict__))
            self._startPage()

        def save(self) -> None:
            page_count = len(self._saved_page_states)
            for state in self._saved_page_states:
                self.__dict__.update(state)
                self._draw_footer(page_count)
                super().showPage()
            super().save()

        def _draw_footer(self, page_count: int) -> None:
            page_width, _ = A4
            self.setFont(regular_font, 7.5)
            self.setFillColor(COLOR_TEXT_MUTED)
            self.drawCentredString(page_width / 2, 14 * mm, footer_text)
            self.drawCentredString(
                page_width / 2,
                9 * mm,
                f"Sayfa {self.getPageNumber()} / {page_count}",
            )

    return NumberedCanvas


def _build_header_flowables(data: InvoiceData, styles: dict) -> list:
    """Üst başlık bantını oluşturur: sistem başlığı (sol) + Bildirim Tarihi
    (sağ), TEK bir bant içinde ortak arka plan/kenarlıkla dikey olarak
    ortalanmış hâlde.

    Önceki tasarımda başlık ve "Bildirim No / Bildirim Tarihi" kutusu farklı
    yükseklikte iki ayrı kutuydu; bu da üstte hizalama bozukluğuna yol
    açıyordu. Artık "Bildirim No" tamamen kaldırıldı ve geri kalan tek satır
    (Bildirim Tarihi), başlıkla AYNI bant/satır içinde `VALIGN=MIDDLE` ile
    hizalanıyor — bu sayede iki taraf da tam ortalanmış ve birbiriyle
    çakışmıyor.
    """
    title_paragraph = Paragraph(data.system_title, styles["system_title"])
    date_paragraph = Paragraph(
        f"Bildirim Tarihi<br/><b>{format_date_tr(data.issue_date)}</b>",
        styles["header_date"],
    )

    header_row = Table(
        [[title_paragraph, date_paragraph]],
        colWidths=[120 * mm, 50 * mm],
    )
    header_row.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), COLOR_LIGHT_BLUE_BG),
                ("BOX", (0, 0), (-1, -1), 0.75, COLOR_PRIMARY_BLUE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (0, 0), "LEFT"),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ("LEFTPADDING", (0, 0), (0, 0), 10),
                ("RIGHTPADDING", (1, 0), (1, 0), 10),
            ]
        )
    )

    return [
        header_row,
        Spacer(1, 4 * mm),
        Paragraph(data.complex_name, styles["complex_name"]),
        Spacer(1, 6 * mm),
    ]


def _section_header(text: str, styles: dict) -> Table:
    table = Table([[Paragraph(text, styles["section_header"])]], colWidths=[170 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), COLOR_PRIMARY_BLUE),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return table


def _build_info_grid(data: InvoiceData, styles: dict) -> Table:
    def cell(label: str, value: str) -> list[Paragraph]:
        return [Paragraph(label, styles["label"]), Paragraph(value, styles["value"])]

    # Not: Bu bölümde eskiden "Hesaplamayı Yapan Kullanıcı" satırı da
    # gösteriliyordu; kullanıcı talebiyle PDF içeriğinden kaldırıldı
    # (`InvoiceData.prepared_by_username` alanı hâlâ mevcut/dolduruluyor —
    # sadece burada GÖSTERİLMİYOR; ileride iç denetim amaçlı kullanılabilir).
    rows_data = [
        (
            cell("Bina", format_optional_text(data.complex_name)),
            cell("Adres", format_optional_text(data.complex_address)),
        ),
        (
            cell("Daire No", format_optional_text(data.unit_no)),
            cell("Sakin", format_optional_text(data.resident_name)),
        ),
        (
            cell("Daire Alanı", format_area(data.apartment_area_m2)),
            cell("Fatura Aralığı", format_date_range_tr(data.window_start, data.window_end)),
        ),
        (
            cell("Kazan Faturası", format_currency(data.boiler_bill)),
            cell("Toplam Bina Alanı", format_area(data.total_building_area_m2)),
        ),
        (
            cell("Toplam Bina Tüketimi", format_energy(data.total_building_energy)),
            cell("Daire Sayısı", str(data.apartment_count)),
        ),
    ]

    table_rows = []
    for left, right in rows_data:
        table_rows.append([left[0], left[1], right[0], right[1]])

    grid = Table(
        table_rows,
        colWidths=[38 * mm, 47 * mm, 38 * mm, 47 * mm],
    )
    grid.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.5, COLOR_TABLE_GRID),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, COLOR_TABLE_GRID),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return grid


def _build_meter_info_table(data: InvoiceData, styles: dict) -> Table:
    """"Sayaç Bilgileri" bölümü: İlk Enerji, Son Enerji ve Tüketim.

    Kümülatif sayaç mantığıyla uyumlu (bkz. billing.services): tüketim
    burada YENİDEN HESAPLANMAZ, `data.energy_consumed` — `billing.services`
    içinde `son - ilk` olarak zaten hesaplanmış değer — olduğu gibi basılır.
    Herhangi bir değer mevcut değilse (ne manuel giriş ne Modbus okuması)
    "—" gösterilir.
    """
    header = [
        Paragraph("İlk Enerji", styles["table_header"]),
        Paragraph("Son Enerji", styles["table_header"]),
        Paragraph("Tüketim (Son − İlk)", styles["table_header"]),
    ]
    values = [
        Paragraph(format_optional_energy(data.start_energy_value), styles["table_cell_right"]),
        Paragraph(format_optional_energy(data.end_energy_value), styles["table_cell_right"]),
        Paragraph(format_optional_energy(data.energy_consumed), styles["table_cell_right"]),
    ]

    table = Table([header, values], colWidths=[56.6 * mm, 56.6 * mm, 56.8 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), COLOR_PRIMARY_BLUE),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("BOX", (0, 0), (-1, -1), 0.5, COLOR_TABLE_GRID),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, COLOR_TABLE_GRID),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return table


def _build_line_items_table(data: InvoiceData, styles: dict) -> Table:
    """Gider Dağılımı tablosu.

    Yönetmelik gereği iki gider kalemi (Sabit Gider Payı, Tüketim Gider
    Payı) ve bunların toplamı (Toplam Ödenecek Tutar) gösterilir. Değerler
    `billing.services` tarafından persist edilmiş `ApartmentBillingLine`'dan
    olduğu gibi gelir; PDF burada hiçbir hesaplama YAPMAZ.
    """
    items = data.line_items
    header = [
        Paragraph("Gider Kalemi", styles["table_header"]),
        Paragraph("Tutar", styles["table_header"]),
    ]
    rows = [
        ("Sabit Gider Payı", format_currency(items.fixed_share)),
        ("Tüketim Gider Payı", format_currency(items.consumption_share)),
    ]

    body = [header]
    for label, value in rows:
        body.append(
            [
                Paragraph(label, styles["table_cell"]),
                Paragraph(value, styles["table_cell_right"]),
            ]
        )
    body.append(
        [
            Paragraph("Toplam Ödenecek Tutar", styles["table_cell_total"]),
            Paragraph(
                format_currency(items.total_payable), styles["table_cell_total"]
            ),
        ]
    )

    table = Table(body, colWidths=[110 * mm, 60 * mm], repeatRows=1)
    style_commands = [
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_PRIMARY_BLUE),
        ("BOX", (0, 0), (-1, -1), 0.5, COLOR_TABLE_GRID),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, COLOR_TABLE_GRID),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, -1), (-1, -1), COLOR_LIGHT_GREEN_BG),
        ("LINEABOVE", (0, -1), (-1, -1), 1, COLOR_ACCENT_GREEN),
    ]
    table.setStyle(TableStyle(style_commands))
    return table


def build_invoice_pdf(data: InvoiceData, output_path: Path) -> Path:
    """`data`'dan bir A4 PDF Gider Bildirimi üretir ve `output_path`'e yazar.

    Args:
        data: PDF'de gösterilecek, önceden hesaplanmış tüm veriler.
        output_path: PDF'nin yazılacağı tam dosya yolu. Üst klasörler
            yoksa oluşturulur.

    Returns:
        Yazılan dosyanın yolu (`output_path` ile aynı).
    """
    register_fonts()
    styles = get_paragraph_styles()

    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=_PAGE_MARGIN,
        rightMargin=_PAGE_MARGIN,
        topMargin=_PAGE_MARGIN,
        bottomMargin=_PAGE_MARGIN + 8 * mm,
        title=f"Gider Bildirimi — {data.unit_no}",
        author=data.system_title,
    )

    story: list = []
    story.extend(_build_header_flowables(data, styles))
    story.append(_section_header("Daire ve Fatura Bilgileri", styles))
    story.append(_build_info_grid(data, styles))
    story.append(Spacer(1, 6 * mm))
    story.append(_section_header("Sayaç Bilgileri", styles))
    story.append(_build_meter_info_table(data, styles))
    story.append(Spacer(1, 6 * mm))
    story.append(_section_header("Gider Dağılımı", styles))
    story.append(_build_line_items_table(data, styles))

    doc.build(story, canvasmaker=_make_numbered_canvas(_FOOTER_TEXT))
    return output_path
