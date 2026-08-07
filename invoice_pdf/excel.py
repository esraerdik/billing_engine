"""
excel.py (invoice_pdf)
-------------------------
`openpyxl` kullanarak bir `BillingRun`'ın TÜM daire sonuçlarını tek bir
Excel (.xlsx) özetine dönüştürür ("Tüm PDF'leri Oluştur" → ZIP akışının
bir parçası).

Bu modül, paketin diğer PDF-özel modülleri (`generator.py`) gibi
Django/ORM'den TAMAMEN HABERSİZDİR — girdisi yalnızca
`invoice_pdf.models.ApartmentSummaryRow` listesidir (saf dataclass'lar);
hiçbir veritabanı sorgusu, hiçbir hesaplama İÇERMEZ. `invoice_pdf.service`
bu satırları `ApartmentBillingLine`'dan inşa eder — PDF ile Excel AYNI
persist edilmiş `BillingSummary` sonucunu okur, ikisi de kendi başına bir
şey hesaplamaz.

Genişletilebilirlik: Yeni bir sütun eklemek için tek yapılması gereken,
`_COLUMNS` tablosuna `(alan_adı, başlık, sayı_biçimi)` şeklinde bir satır
eklemektir — bu fonksiyonların hiçbiri değişmez.
"""

from __future__ import annotations

from dataclasses import fields as dataclass_fields
from decimal import Decimal
from io import BytesIO
from typing import Sequence

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from .formatters import format_optional_text
from .models import ApartmentSummaryRow

_CURRENCY_FORMAT = '#,##0.00" TL"'
_NUMBER_FORMAT = "#,##0.00"
_HEADER_FONT = Font(bold=True, color="FFFFFF")
_HEADER_FILL_COLOR = "2563EB"  # bkz. styles.COLOR_PRIMARY_BLUE — panelle tutarlı
_MIN_COLUMN_WIDTH = 10
_MAX_COLUMN_WIDTH = 45
_SHEET_TITLE = "Fatura Özeti"

# (ApartmentSummaryRow alanı, sütun başlığı, sayı biçimi veya None [metin]).
# Yeni bir hesaplama kalemi eklenmek istendiğinde YALNIZCA bu listeye bir
# satır eklenir — `build_summary_workbook` ve altındaki her şey aynen
# çalışmaya devam eder.
_COLUMNS: list[tuple[str, str, str | None]] = [
    ("complex_name", "Apartman", None),
    ("block", "Blok", None),
    ("unit_no", "Daire No", None),
    ("resident_name", "Kullanıcı / Malik", None),
    ("area_m2", "Alan (m²)", _NUMBER_FORMAT),
    ("start_energy_value", "İlk Enerji", _NUMBER_FORMAT),
    ("end_energy_value", "Son Enerji", _NUMBER_FORMAT),
    ("energy_consumed", "Tüketim", _NUMBER_FORMAT),
    ("fixed_share", "Sabit Gider Payı", _CURRENCY_FORMAT),
    ("consumption_share", "Tüketim Gider Payı", _CURRENCY_FORMAT),
    ("total_payable", "Toplam Ödenecek Tutar", _CURRENCY_FORMAT),
]

_TEXT_FIELDS = {"complex_name", "block", "unit_no", "resident_name"}


def _validate_columns() -> None:
    """`_COLUMNS`'taki her alan adının `ApartmentSummaryRow`'da gerçekten
    var olduğunu doğrular — sütun tablosuna yazım hatasıyla yanlış bir
    alan adı eklenmesi hâlinde ilk PDF/Excel üretiminde SESSİZCE hatalı
    veri yerine anlaşılır bir `AttributeError`/`AssertionError` alınsın.
    """
    valid_names = {f.name for f in dataclass_fields(ApartmentSummaryRow)}
    for field_name, _, _ in _COLUMNS:
        if field_name not in valid_names:
            raise AssertionError(
                f"invoice_pdf.excel._COLUMNS: '{field_name}' ApartmentSummaryRow'da yok."
            )


def _cell_value(row: ApartmentSummaryRow, field_name: str):
    value = getattr(row, field_name)
    if field_name in _TEXT_FIELDS:
        return format_optional_text(value if value else None)
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _autosize_columns(sheet: Worksheet, column_count: int) -> None:
    """Her sütunun genişliğini, o sütundaki en uzun hücre metnine göre
    otomatik ayarlar (openpyxl'de yerleşik bir "autosize" olmadığından
    standart bir yaklaşım: en uzun metin uzunluğu + küçük bir pay).
    """
    for col_index in range(1, column_count + 1):
        letter = get_column_letter(col_index)
        max_length = 0
        for cell in sheet[letter]:
            if cell.value is None:
                continue
            text = f"{cell.value}"
            max_length = max(max_length, len(text))
        width = max(_MIN_COLUMN_WIDTH, min(_MAX_COLUMN_WIDTH, max_length + 3))
        sheet.column_dimensions[letter].width = width


def build_summary_workbook(rows: Sequence[ApartmentSummaryRow]) -> Workbook:
    """`rows`'tan, her satırı bir daireye karşılık gelen tek sayfalı bir
    `Workbook` üretir.

    Sayfa başlıkları kalın (bold) ve dondurulmuş (freeze pane) olur; para
    sütunları TL biçiminde, sayısal sütunlar (alan/enerji) iki ondalıklı
    biçimde gösterilir. Buradaki hiçbir değer YENİDEN HESAPLANMAZ — girdi
    olarak verilenler olduğu gibi hücrelere yazılır.
    """
    _validate_columns()

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = _SHEET_TITLE

    header_fill = PatternFill(
        start_color=_HEADER_FILL_COLOR, end_color=_HEADER_FILL_COLOR, fill_type="solid"
    )
    headers = [label for _, label, _ in _COLUMNS]
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.fill = header_fill

    for row in rows:
        values = [_cell_value(row, field_name) for field_name, _, _ in _COLUMNS]
        sheet.append(values)

    last_row = sheet.max_row
    for col_index, (_, _, number_format) in enumerate(_COLUMNS, start=1):
        if number_format is None:
            continue
        letter = get_column_letter(col_index)
        for row_index in range(2, last_row + 1):
            sheet[f"{letter}{row_index}"].number_format = number_format

    sheet.freeze_panes = "A2"
    _autosize_columns(sheet, len(_COLUMNS))

    return workbook


def write_summary_workbook_to_bytes(rows: Sequence[ApartmentSummaryRow]) -> bytes:
    """`build_summary_workbook`'un sonucunu, diske hiç yazmadan bellekte
    (`BytesIO`) `.xlsx` bayt dizisine dönüştürür — doğrudan bir ZIP
    arşivine veya `HttpResponse`'a yazılabilir."""
    workbook = build_summary_workbook(rows)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
