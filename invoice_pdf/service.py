"""
service.py (invoice_pdf)
---------------------------
Bu paketteki TEK Django/ORM'e bağımlı modül.

Sorumluluğu: kalıcı hâle gelmiş faturalandırma kayıtlarından
(`billing.models.BillingRun` / `ApartmentBillingLine`) saf bir
`invoice_pdf.models.InvoiceData` inşa etmek, `invoice_pdf.generator` ile
PDF'e dönüştürmek, diskte `generated_invoices/<yıl>/<ay>/` altına
yazmak (var olan bir dosyanın üzerine YAZMAMAK) ve bir çalıştırmanın tüm
PDF'lerini ZIP'lemek.

`billing.services` bu modülü çağırır (`billing.services` →
`invoice_pdf.service` → `billing.models`); ters yönde HİÇBİR import yoktur
— `invoice_pdf` paketinin geri kalanı (`generator.py`, `formatters.py`,
`styles.py`, `models.py`) Django'dan tamamen habersizdir.
"""

from __future__ import annotations

import re
import zipfile
from io import BytesIO
from pathlib import Path

from django.conf import settings

from billing.models import (
    ApartmentBillingLine,
    ApartmentResident,
    BillingRun,
)

from .excel import write_summary_workbook_to_bytes
from .generator import build_invoice_pdf
from .models import ApartmentSummaryRow, InvoiceData, InvoiceLineItems

_SYSTEM_TITLE = "Merkezi Isıtma Gider Paylaşım Sistemi"
_SAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _sanitize_for_filename(value: str) -> str:
    """Dosya adına gömülecek bir metni dosya sistemi için güvenli hale getirir."""
    cleaned = _SAFE_CHARS_RE.sub("-", value.strip())
    return cleaned.strip("-_") or "daire"


def _invoice_number(line: ApartmentBillingLine) -> str:
    """Bildirim numarası: `ApartmentBillingLine.id` — benzersiz, otomatik
    artan, yeni bir sayaç tablosu gerektirmez."""
    return f"{line.id:06d}"


def _invoice_output_path(line: ApartmentBillingLine) -> Path:
    run = line.billing_run
    apartment = line.apartment
    year_dir = f"{run.period_year:04d}"
    month_dir = f"{run.period_month:02d}"
    filename = (
        f"{run.period_year:04d}-{run.period_month:02d}"
        f"_Daire-{_sanitize_for_filename(apartment.unit_no)}"
        f"_Fatura-{_invoice_number(line)}.pdf"
    )
    base_dir = Path(settings.GENERATED_INVOICES_DIR)
    return base_dir / year_dir / month_dir / filename


def _current_resident_name(apartment) -> str | None:
    resident = (
        ApartmentResident.objects.filter(apartment=apartment, ended_at__isnull=True)
        .order_by("-started_at")
        .first()
    )
    return resident.name if resident else None


def _build_invoice_data(line: ApartmentBillingLine) -> InvoiceData:
    """Bir `ApartmentBillingLine`'dan PDF'e özgü, saf `InvoiceData`'yı inşa eder.

    Bu fonksiyon dışında hiçbir yer ORM alanlarını `invoice_pdf`'in
    dataclass alanlarına eşlemez — tüm "PDF için veri nereden geliyor"
    kararı burada tek bir noktada toplanmıştır.
    """
    run: BillingRun = line.billing_run
    apartment = line.apartment
    complex_obj = apartment.complex

    line_items = InvoiceLineItems(
        fixed_share=line.fixed_share,
        consumption_share=line.consumption_share,
        total_payable=line.total_payable,
    )

    return InvoiceData(
        invoice_number=_invoice_number(line),
        issue_date=run.recorded_at.date(),
        system_title=_SYSTEM_TITLE,
        complex_name=complex_obj.name,
        complex_address=complex_obj.address or None,
        unit_no=apartment.unit_no,
        resident_name=_current_resident_name(apartment),
        prepared_by_username=run.run_by.username,
        apartment_area_m2=apartment.area_m2,
        window_start=run.window_start_date,
        window_end=run.window_end_date,
        boiler_bill=run.total_bill,
        total_building_area_m2=run.total_area,
        total_building_energy=run.total_energy,
        apartment_count=run.lines.count(),
        # Kümülatif sayaç endeksleri (bkz. billing.services
        # `_ApartmentEnergyMeta`) — manuel giriş veya (ileride) Modbus
        # okumasından gelir; ikisi de yoksa `None` ("—" gösterilir).
        start_energy_value=line.start_energy_value,
        end_energy_value=line.end_energy_value,
        energy_consumed=line.energy_consumed,
        line_items=line_items,
    )


def _build_summary_row(line: ApartmentBillingLine) -> ApartmentSummaryRow:
    """Bir `ApartmentBillingLine`'dan, toplu Excel özetindeki TEK satırı
    inşa eder.

    `_build_invoice_data` (PDF) ile birebir AYNI kaynak alanları kullanır
    — ikisi de aynı satırdan okur, aralarında hiçbir hesaplama farkı
    yoktur (bkz. bu modülün docstring'i).
    """
    apartment = line.apartment
    complex_obj = apartment.complex

    return ApartmentSummaryRow(
        complex_name=complex_obj.name,
        block=apartment.block,
        unit_no=apartment.unit_no,
        resident_name=_current_resident_name(apartment),
        area_m2=apartment.area_m2,
        start_energy_value=line.start_energy_value,
        end_energy_value=line.end_energy_value,
        energy_consumed=line.energy_consumed,
        fixed_share=line.fixed_share,
        consumption_share=line.consumption_share,
        total_payable=line.total_payable,
    )


def build_summary_rows_for_run(billing_run: BillingRun) -> list[ApartmentSummaryRow]:
    """Bir `BillingRun`'a ait TÜM dairelerin Excel özet satırlarını, daire
    numarasına göre sıralı olarak döndürür."""
    lines = (
        ApartmentBillingLine.objects.filter(billing_run=billing_run)
        .select_related("apartment", "apartment__complex")
        .order_by("apartment__unit_no")
    )
    return [_build_summary_row(line) for line in lines]


def generate_invoice_for_line(line: ApartmentBillingLine) -> Path:
    """Bir daire satırının PDF'ini üretir (veya zaten varsa dosyasını döndürür).

    Aynı yol zaten mevcutsa dosya YENİDEN ÜRETİLMEZ — bildirim numarası
    (`ApartmentBillingLine.id`) ve dolayısıyla dosya adı bire bir aynı
    veriye karşılık geldiğinden, bu idempotent bir davranıştır ve
    "aynı isim varsa üzerine yazılmasın" kuralını karşılar.
    """
    output_path = _invoice_output_path(line)
    if output_path.exists():
        return output_path

    data = _build_invoice_data(line)
    return build_invoice_pdf(data, output_path)


def generate_invoices_for_run(billing_run: BillingRun) -> list[Path]:
    """Bir `BillingRun`'a ait TÜM dairelerin PDF'lerini üretir.

    Zaten üretilmiş olanlar atlanır (bkz. `generate_invoice_for_line`).
    Sonuç, daire numarasına göre sıralı bir yol listesidir.
    """
    lines = (
        ApartmentBillingLine.objects.filter(billing_run=billing_run)
        .select_related(
            "billing_run",
            "billing_run__run_by",
            "apartment",
            "apartment__complex",
        )
        .order_by("apartment__unit_no")
    )
    return [generate_invoice_for_line(line) for line in lines]


def get_invoice_path_for_apartment(billing_run: BillingRun, apartment_id: int) -> Path:
    """Belirtilen çalıştırma + daire için PDF yolunu döndürür (yoksa üretir)."""
    line = ApartmentBillingLine.objects.select_related(
        "billing_run",
        "billing_run__run_by",
        "apartment",
        "apartment__complex",
    ).get(billing_run=billing_run, apartment_id=apartment_id)
    return generate_invoice_for_line(line)


def _zip_pdf_arcname(unit_no: str) -> str:
    """ZIP içindeki PDF adı: örn. "Daire-001.pdf".

    Daire no saf sayısal ise ("1", "12" gibi) örnekteki gibi 3 haneli
    sıfır doldurmalı biçime getirilir ("Daire-001.pdf"); alfanümerik bir
    daire no ise ("A-101" gibi) olduğu gibi (dosya sistemi için
    temizlenmiş hâliyle) kullanılır — rastgele bir sayı UYDURULMAZ.
    """
    if unit_no.strip().isdigit():
        return f"Daire-{int(unit_no):03d}.pdf"
    return f"Daire-{_sanitize_for_filename(unit_no)}.pdf"


def _summary_excel_filename(billing_run: BillingRun) -> str:
    return f"{billing_run.period_year:04d}-{billing_run.period_month:02d}_Fatura_Ozeti.xlsx"


def _zip_filename(billing_run: BillingRun) -> str:
    return f"{billing_run.period_year:04d}-{billing_run.period_month:02d}_Faturalar.zip"


def build_zip_for_run(billing_run: BillingRun) -> tuple[BytesIO, str]:
    """Bir çalıştırmanın tüm daire PDF'lerini VE tek bir toplu Excel
    özetini bellekte bir ZIP'e paketler.

    ZIP içeriği (örn. "2026-08_Faturalar.zip"):
        2026-08_Fatura_Ozeti.xlsx  ← `invoice_pdf.excel`, TÜM daireler
        Daire-001.pdf              ← her daire için tekil Gider Bildirimi
        Daire-002.pdf
        ...

    Excel özeti PDF'lerle AYNI `ApartmentBillingLine` kayıtlarından (yani
    aynı persist edilmiş `BillingSummary` sonucundan) inşa edilir — hiçbir
    hesaplama burada TEKRARLANMAZ (bkz. `build_summary_rows_for_run`).
    Eksik PDF'ler önce üretilir (bkz. `generate_invoices_for_run`).

    Returns:
        `(zip_buffer, önerilen_dosya_adı)` — `zip_buffer` başa sarılmış
        (`seek(0)`) bir `BytesIO`'dur, doğrudan bir `HttpResponse`'a
        yazılabilir.
    """
    lines = (
        ApartmentBillingLine.objects.filter(billing_run=billing_run)
        .select_related(
            "billing_run",
            "billing_run__run_by",
            "apartment",
            "apartment__complex",
        )
        .order_by("apartment__unit_no")
    )
    lines = list(lines)

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        summary_rows = [_build_summary_row(line) for line in lines]
        excel_bytes = write_summary_workbook_to_bytes(summary_rows)
        archive.writestr(_summary_excel_filename(billing_run), excel_bytes)

        for line in lines:
            pdf_path = generate_invoice_for_line(line)
            archive.write(pdf_path, arcname=_zip_pdf_arcname(line.apartment.unit_no))
    buffer.seek(0)

    return buffer, _zip_filename(billing_run)
