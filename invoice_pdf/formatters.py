"""
formatters.py (invoice_pdf)
-----------------------------
PDF'de gösterilecek değerlerin (para, tarih, alan, oran) biçimlendirme
yardımcıları.

`locale` modülüne KASITLI OLARAK bağımlı değildir: sunucu ortamının
`tr_TR` locale'i kurulu olup olmamasına göre davranış değiştirmemesi için
tüm biçimlendirme string manipülasyonuyla elle yapılır — bu, farklı
işletim sistemlerinde (Windows/Linux) ve konteynerlerde deterministik ve
taşınabilir kalmasını sağlar.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

_EM_DASH = "—"

_TR_MONTHS = {
    1: "Ocak",
    2: "Şubat",
    3: "Mart",
    4: "Nisan",
    5: "Mayıs",
    6: "Haziran",
    7: "Temmuz",
    8: "Ağustos",
    9: "Eylül",
    10: "Ekim",
    11: "Kasım",
    12: "Aralık",
}


def format_currency(value: Decimal | int | float) -> str:
    """Bir tutarı Türkçe para biçiminde döndürür: "12.450,75 TL".

    Args:
        value: Biçimlendirilecek tutar. `Decimal` olması beklenir; `int`/
            `float` verilirse önce `Decimal`'e çevrilir (hassasiyet kaybını
            önlemek için `str()` üzerinden).

    Returns:
        Binlik ayıracı "." , ondalık ayıracı "," olan, " TL" son ekli,
        her zaman 2 ondalık haneli bir metin.
    """
    if not isinstance(value, Decimal):
        value = Decimal(str(value))

    quantized = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = "-" if quantized < 0 else ""
    quantized = abs(quantized)

    integer_part, _, fractional_part = f"{quantized:f}".partition(".")
    fractional_part = (fractional_part + "00")[:2]

    grouped_chars: list[str] = []
    for index, digit in enumerate(reversed(integer_part)):
        if index and index % 3 == 0:
            grouped_chars.append(".")
        grouped_chars.append(digit)
    grouped_integer = "".join(reversed(grouped_chars))

    return f"{sign}{grouped_integer},{fractional_part} TL"


def format_optional_currency(value: Decimal | int | float | None) -> str:
    """`format_currency` ile aynıdır; `None` için em-dash ("—") döndürür.

    Değeri opsiyonel (bulunmayabilir) olan parasal alanların gösteriminde
    kullanılan genel bir yardımcıdır.
    """
    if value is None:
        return _EM_DASH
    return format_currency(value)


def format_area(value: Decimal | int | float) -> str:
    """Bir alan değerini "123,45 m²" biçiminde döndürür."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    quantized = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    text = f"{quantized:f}".replace(".", ",")
    return f"{text} m²"


def format_energy(value: Decimal | int | float) -> str:
    """Bir enerji tüketim değerini iki ondalıklı, Türkçe ayraçlı döndürür."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    quantized = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{quantized:f}".replace(".", ",")


def format_optional_energy(value: Decimal | int | float | None) -> str:
    """`format_energy` ile aynıdır; `None` için em-dash ("—") döndürür.

    Manuel girişi olmayan ve henüz Modbus okuması bulunmayan bir daire için
    "İlk Enerji"/"Son Enerji"/"Tüketim" alanlarının hiçbiri mevcut olmayabilir
    — bkz. `invoice_pdf.models.InvoiceData.start_energy_value` vb.
    """
    if value is None:
        return _EM_DASH
    return format_energy(value)


def format_ratio_percent(value: Decimal | float) -> str:
    """Bir oranı (0-1 arası) yüzde biçiminde döndürür: "%42,50"."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    percent = (value * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"%{f'{percent:f}'.replace('.', ',')}"


def format_date_tr(value: date) -> str:
    """Bir tarihi "05 Ağustos 2026" biçiminde döndürür."""
    return f"{value.day:02d} {_TR_MONTHS[value.month]} {value.year}"


def format_date_range_tr(start: date, end: date) -> str:
    """İki tarihi " — " ile ayırarak Türkçe biçimde döndürür."""
    return f"{format_date_tr(start)} — {format_date_tr(end)}"


def format_optional_text(value: str | None) -> str:
    """Boş/`None` bir metin alanı için em-dash ("—"), aksi halde metnin
    kendisini döndürür."""
    if value is None or not value.strip():
        return _EM_DASH
    return value
