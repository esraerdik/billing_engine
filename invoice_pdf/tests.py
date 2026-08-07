"""
tests.py (invoice_pdf)
-------------------------
`invoice_pdf` paketi için testler. İki katmana ayrılır:

    - DB'siz `unittest.TestCase`ler: `formatters.py` ve `generator.py`
      Django/ORM'den habersiz olduğu için doğrudan saf `InvoiceData` ile
      test edilir (bkz. `FormattersTests`, `GeneratorTests`).
    - Django `TestCase`: `service.py` gerçek `BillingRun`/
      `ApartmentBillingLine` kayıtlarına ihtiyaç duyduğu için veritabanı
      gerektirir (bkz. `InvoicePdfServiceTests`).

Çalıştırmak için:
    python manage.py test invoice_pdf -v 2
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
import zipfile
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from pypdf import PdfReader

from billing.models import (
    Apartment,
    ApartmentBillingLine,
    ApartmentComplex,
    BillingRun,
)

from openpyxl import load_workbook

from .excel import build_summary_workbook, write_summary_workbook_to_bytes
from .formatters import (
    format_area,
    format_currency,
    format_date_range_tr,
    format_date_tr,
    format_optional_currency,
    format_optional_text,
)
from .generator import build_invoice_pdf
from .models import ApartmentSummaryRow, InvoiceData, InvoiceLineItems
from .service import (
    build_summary_rows_for_run,
    build_zip_for_run,
    generate_invoice_for_line,
    generate_invoices_for_run,
    get_invoice_path_for_apartment,
)


def _sample_invoice_data(**overrides) -> InvoiceData:
    defaults = dict(
        invoice_number="000001",
        issue_date=date(2026, 8, 5),
        system_title="Merkezi Isıtma Gider Paylaşım Sistemi",
        complex_name="Güneşli Apartmanı",
        complex_address="Çiçek Sok. No:5, İstanbul",
        unit_no="11",
        resident_name="Şükrü Öztürk",
        prepared_by_username="admin",
        apartment_area_m2=Decimal("120.00"),
        window_start=date(2026, 1, 1),
        window_end=date(2026, 1, 31),
        boiler_bill=Decimal("45000.00"),
        total_building_area_m2=Decimal("465.00"),
        total_building_energy=Decimal("4890.00"),
        apartment_count=4,
        start_energy_value=Decimal("1000.00"),
        end_energy_value=Decimal("1333.33"),
        energy_consumed=Decimal("333.33"),
        line_items=InvoiceLineItems(
            fixed_share=Decimal("3612.90"),
            consumption_share=Decimal("8032.72"),
            total_payable=Decimal("11645.62"),
        ),
    )
    defaults.update(overrides)
    return InvoiceData(**defaults)


def _sample_summary_row(**overrides) -> ApartmentSummaryRow:
    defaults = dict(
        complex_name="Güneşli Apartmanı",
        block="A Blok",
        unit_no="11",
        resident_name="Şükrü Öztürk",
        area_m2=Decimal("120.00"),
        start_energy_value=Decimal("1000.00"),
        end_energy_value=Decimal("1333.33"),
        energy_consumed=Decimal("333.33"),
        fixed_share=Decimal("300.00"),
        consumption_share=Decimal("700.00"),
        total_payable=Decimal("1000.00"),
    )
    defaults.update(overrides)
    return ApartmentSummaryRow(**defaults)


class FormattersTests(unittest.TestCase):
    """`formatters.py` — Decimal tabanlı biçimleme yardımcıları."""

    def test_format_currency_basic(self) -> None:
        self.assertEqual(format_currency(Decimal("45.5")), "45,50 TL")

    def test_format_currency_thousands_separator(self) -> None:
        self.assertEqual(format_currency(Decimal("12450.75")), "12.450,75 TL")

    def test_format_currency_millions_separator(self) -> None:
        self.assertEqual(format_currency(Decimal("1234567.9")), "1.234.567,90 TL")

    def test_format_currency_accepts_float(self) -> None:
        self.assertEqual(format_currency(1000.0), "1.000,00 TL")

    def test_format_currency_negative(self) -> None:
        self.assertEqual(format_currency(Decimal("-45.5")), "-45,50 TL")

    def test_format_optional_currency_none_is_dash(self) -> None:
        self.assertEqual(format_optional_currency(None), "—")

    def test_format_optional_currency_value(self) -> None:
        self.assertEqual(format_optional_currency(Decimal("10")), "10,00 TL")

    def test_format_area(self) -> None:
        self.assertEqual(format_area(Decimal("120")), "120,00 m²")

    def test_format_date_tr(self) -> None:
        self.assertEqual(format_date_tr(date(2026, 8, 5)), "05 Ağustos 2026")

    def test_format_date_range_tr(self) -> None:
        result = format_date_range_tr(date(2026, 1, 1), date(2026, 1, 31))
        self.assertEqual(result, "01 Ocak 2026 — 31 Ocak 2026")

    def test_format_optional_text_none_is_dash(self) -> None:
        self.assertEqual(format_optional_text(None), "—")

    def test_format_optional_text_blank_is_dash(self) -> None:
        self.assertEqual(format_optional_text("   "), "—")

    def test_format_optional_text_value(self) -> None:
        self.assertEqual(format_optional_text("Şükrü Öztürk"), "Şükrü Öztürk")


class GeneratorTests(unittest.TestCase):
    """`generator.py` — Django'dan habersiz, saf `InvoiceData` ile PDF üretimi."""

    def setUp(self) -> None:
        self._tmp_dir = Path(tempfile.mkdtemp(prefix="invoice_pdf_test_"))
        self.addCleanup(shutil.rmtree, self._tmp_dir, ignore_errors=True)

    def _extract_text(self, pdf_path: Path) -> str:
        reader = PdfReader(str(pdf_path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    def test_pdf_is_generated_as_valid_pdf_file(self) -> None:
        output_path = self._tmp_dir / "test-invoice.pdf"
        result_path = build_invoice_pdf(_sample_invoice_data(), output_path)

        self.assertEqual(result_path, output_path)
        self.assertTrue(output_path.exists())
        self.assertGreater(output_path.stat().st_size, 0)
        with open(output_path, "rb") as handle:
            self.assertEqual(handle.read(5), b"%PDF-")

    def test_pdf_creates_missing_parent_directories(self) -> None:
        output_path = self._tmp_dir / "nested" / "dirs" / "invoice.pdf"
        build_invoice_pdf(_sample_invoice_data(), output_path)
        self.assertTrue(output_path.exists())

    def test_turkish_characters_render_correctly(self) -> None:
        output_path = self._tmp_dir / "turkish.pdf"
        build_invoice_pdf(_sample_invoice_data(), output_path)
        text = self._extract_text(output_path)

        for expected in [
            "Isıtma",
            "Güneşli Apartmanı",
            "Çiçek Sok",
            "İstanbul",
            "Şükrü Öztürk",
            "Ağustos",
            "Ödenecek",
            "İlk Enerji",
        ]:
            self.assertIn(expected, text, f"Beklenen Türkçe metin bulunamadı: {expected!r}")

    def test_line_items_table_shows_fixed_consumption_and_total(self) -> None:
        """Gider Dağılımı tablosu yalnızca Sabit Gider Payı, Tüketim Gider
        Payı ve Toplam Ödenecek Tutar'ı gösterir; verilen değerler PDF'de
        yeniden hesaplanmadan olduğu gibi basılır."""
        output_path = self._tmp_dir / "line-items.pdf"
        data = _sample_invoice_data(
            line_items=InvoiceLineItems(
                fixed_share=Decimal("100.00"),
                consumption_share=Decimal("200.00"),
                total_payable=Decimal("300.00"),
            )
        )
        build_invoice_pdf(data, output_path)
        text = self._extract_text(output_path)

        self.assertIn("Sabit Gider Payı", text)
        self.assertIn("Tüketim Gider Payı", text)
        self.assertIn("Toplam Ödenecek Tutar", text)
        self.assertIn("100,00 TL", text)
        self.assertIn("200,00 TL", text)
        self.assertIn("300,00 TL", text)

    def test_reference_consumption_correction_is_not_present(self) -> None:
        """15°C Referans Tüketim Düzeltmesi özelliği tamamen kaldırıldı —
        ne satır ne de "Düzeltilmiş"/"Nihai" ibareleri PDF'de görünmemeli."""
        output_path = self._tmp_dir / "no-15c.pdf"
        build_invoice_pdf(_sample_invoice_data(), output_path)
        text = self._extract_text(output_path)

        for removed in [
            "15°C",
            "Referans Tüketim Düzeltmesi",
            "Düzeltilmiş Tüketim Payı",
            "Nihai Ödenecek Tutar",
        ]:
            self.assertNotIn(removed, text, f"Kaldırılmış ibare hâlâ PDF'de: {removed!r}")

    def test_removed_expense_items_are_not_present(self) -> None:
        """Kullanıcı talebiyle kaldırılan dört kalem, ne tabloda ne de
        toplam hesap kısmında görünmemeli."""
        output_path = self._tmp_dir / "removed-items.pdf"
        build_invoice_pdf(_sample_invoice_data(), output_path)
        text = self._extract_text(output_path)

        for removed in ["Ortak Alan Gideri", "Hizmet Bedeli", "Ek Ödeme", "İndirim"]:
            self.assertNotIn(removed, text, f"Kaldırılmış kalem hâlâ PDF'de: {removed!r}")

    def test_invoice_number_not_shown_in_header(self) -> None:
        """Bildirim numarası artık üst başlıkta GÖSTERİLMEZ (yalnızca
        dosya adında/iç kayıtta kullanılır)."""
        output_path = self._tmp_dir / "no-invoice-number.pdf"
        build_invoice_pdf(_sample_invoice_data(invoice_number="000042"), output_path)
        text = self._extract_text(output_path)

        self.assertNotIn("Bildirim No", text)
        self.assertNotIn("000042", text)
        self.assertIn("Bildirim Tarihi", text)

    def test_meter_info_section_shows_start_end_and_consumption(self) -> None:
        output_path = self._tmp_dir / "meter-info.pdf"
        data = _sample_invoice_data(
            start_energy_value=Decimal("1000.00"),
            end_energy_value=Decimal("1450.75"),
            energy_consumed=Decimal("450.75"),
        )
        build_invoice_pdf(data, output_path)
        text = self._extract_text(output_path)

        self.assertIn("Sayaç Bilgileri", text)
        self.assertIn("İlk Enerji", text)
        self.assertIn("Son Enerji", text)
        self.assertIn("1000,00", text)
        self.assertIn("1450,75", text)
        self.assertIn("450,75", text)
        self.assertNotIn("Enerji (Wh)", text)

    def test_meter_info_section_shows_dash_when_no_energy_data(self) -> None:
        output_path = self._tmp_dir / "meter-info-empty.pdf"
        data = _sample_invoice_data(
            start_energy_value=None,
            end_energy_value=None,
            energy_consumed=None,
        )
        build_invoice_pdf(data, output_path)
        text = self._extract_text(output_path)

        self.assertIn("Sayaç Bilgileri", text)
        self.assertIn("—", text)

    def test_prepared_by_user_section_not_shown(self) -> None:
        """Kullanıcı talebiyle "Hesaplamayı Yapan Kullanıcı" bölümü PDF'den
        kaldırıldı — `InvoiceData.prepared_by_username` alanı hâlâ mevcut
        olsa da (iç kayıt amaçlı) artık PDF içeriğinde GÖSTERİLMEZ."""
        output_path = self._tmp_dir / "no-prepared-by.pdf"
        build_invoice_pdf(_sample_invoice_data(prepared_by_username="admin"), output_path)
        text = self._extract_text(output_path)

        self.assertNotIn("Hesaplamayı Yapan Kullanıcı", text)


class ExcelTests(unittest.TestCase):
    """`excel.py` — Django'dan habersiz, saf `ApartmentSummaryRow` listesiyle
    openpyxl tabanlı toplu Excel özeti üretimi."""

    def test_headers_are_bold_and_match_expected_columns(self) -> None:
        workbook = build_summary_workbook([_sample_summary_row()])
        sheet = workbook.active
        header_cells = sheet[1]
        headers = [cell.value for cell in header_cells]

        self.assertEqual(
            headers,
            [
                "Apartman",
                "Blok",
                "Daire No",
                "Kullanıcı / Malik",
                "Alan (m²)",
                "İlk Enerji",
                "Son Enerji",
                "Tüketim",
                "Sabit Gider Payı",
                "Tüketim Gider Payı",
                "Toplam Ödenecek Tutar",
            ],
        )
        for cell in header_cells:
            self.assertTrue(cell.font.bold, f"Başlık hücresi kalın değil: {cell.value!r}")

    def test_one_row_per_apartment_with_correct_values(self) -> None:
        rows = [
            _sample_summary_row(unit_no="1", total_payable=Decimal("1000.00")),
            _sample_summary_row(unit_no="2", total_payable=Decimal("2000.00")),
            _sample_summary_row(unit_no="3", total_payable=Decimal("3000.00")),
        ]
        workbook = build_summary_workbook(rows)
        sheet = workbook.active

        self.assertEqual(sheet.max_row, 4)  # 1 başlık + 3 daire
        unit_no_values = [sheet.cell(row=r, column=3).value for r in range(2, 5)]
        self.assertEqual(unit_no_values, ["1", "2", "3"])
        total_values = [sheet.cell(row=r, column=11).value for r in range(2, 5)]
        self.assertEqual(total_values, [1000.0, 2000.0, 3000.0])

    def test_currency_columns_use_tl_number_format(self) -> None:
        workbook = build_summary_workbook([_sample_summary_row()])
        sheet = workbook.active
        # Sabit=9, Tüketim=10, Toplam=11.
        for col in (9, 10, 11):
            self.assertIn("TL", sheet.cell(row=2, column=col).number_format)

    def test_numeric_columns_use_two_decimal_number_format(self) -> None:
        workbook = build_summary_workbook([_sample_summary_row()])
        sheet = workbook.active
        # Alan = 5, İlk Enerji = 6, Son Enerji = 7, Tüketim = 8.
        for col in (5, 6, 7, 8):
            self.assertEqual(sheet.cell(row=2, column=col).number_format, "#,##0.00")

    def test_missing_energy_values_leave_cell_blank_not_dash(self) -> None:
        row = _sample_summary_row(
            start_energy_value=None, end_energy_value=None, energy_consumed=None
        )
        workbook = build_summary_workbook([row])
        sheet = workbook.active
        self.assertIsNone(sheet.cell(row=2, column=6).value)
        self.assertIsNone(sheet.cell(row=2, column=7).value)
        self.assertIsNone(sheet.cell(row=2, column=8).value)

    def test_missing_text_fields_render_as_dash(self) -> None:
        row = _sample_summary_row(block="", resident_name=None)
        workbook = build_summary_workbook([row])
        sheet = workbook.active
        self.assertEqual(sheet.cell(row=2, column=2).value, "—")
        self.assertEqual(sheet.cell(row=2, column=4).value, "—")

    def test_column_widths_are_autosized(self) -> None:
        rows = [_sample_summary_row(complex_name="Çok Uzun Bir Apartman Adı A.Ş.")]
        workbook = build_summary_workbook(rows)
        sheet = workbook.active
        width = sheet.column_dimensions["A"].width
        self.assertGreater(width, 15)

    def test_write_summary_workbook_to_bytes_is_valid_xlsx(self) -> None:
        data = write_summary_workbook_to_bytes([_sample_summary_row()])
        self.assertIsInstance(data, bytes)
        self.assertGreater(len(data), 0)
        # xlsx dosyaları ZIP tabanlıdır — "PK" imzasıyla başlar.
        self.assertEqual(data[:2], b"PK")

    def test_no_recalculation_values_pass_through_unchanged(self) -> None:
        """Excel, girdi olarak verilen `total_payable`'ı OLDUĞU GİBİ yazar —
        `fixed_share + consumption_share` toplamını kendisi hesaplamaz."""
        row = _sample_summary_row(
            fixed_share=Decimal("111.11"),
            consumption_share=Decimal("222.22"),
            total_payable=Decimal("999.99"),  # kasıtlı olarak toplamla uyuşmuyor
        )
        workbook = build_summary_workbook([row])
        sheet = workbook.active
        self.assertEqual(sheet.cell(row=2, column=11).value, 999.99)


@override_settings()
class InvoicePdfServiceTests(TestCase):
    """`service.py` — gerçek `BillingRun`/`ApartmentBillingLine` kayıtlarıyla
    uçtan uca PDF/ZIP üretimi (Django ORM gerektirir)."""

    def setUp(self) -> None:
        # Not: Bu dizin bilinçli olarak HER TEST İÇİN AYRI oluşturulur
        # (sınıf seviyesinde DEĞİL). Django `TestCase`, her test metodunu
        # bir transaction içine alıp SONUNDA GERİ ALIR (rollback); SQLite
        # bu durumda otomatik artan ID'leri (örn. `ApartmentBillingLine.id`)
        # bir SONRAKİ testte YENİDEN KULLANABİLİR. PDF dosya adı bu ID'yi
        # içerdiğinden (`_invoice_number`), sınıf seviyesinde PAYLAŞILAN
        # bir dizin kullanmak, önceki bir testte üretilmiş "aynı isimli"
        # ama farklı içerikli bir PDF'in idempotent "üzerine yazma"
        # kuralı yüzünden YANLIŞLIKLA yeniden kullanılmasına yol açabilir.
        self._tmp_media_dir = Path(
            tempfile.mkdtemp(prefix="invoice_pdf_service_test_")
        )
        self.addCleanup(shutil.rmtree, self._tmp_media_dir, ignore_errors=True)

        self._settings_override = override_settings(
            GENERATED_INVOICES_DIR=self._tmp_media_dir
        )
        self._settings_override.enable()
        self.addCleanup(self._settings_override.disable)

        self.user = User.objects.create_user(username="test-runner", password="x")
        self.complex = ApartmentComplex.objects.create(
            name="Test Apartmanı", address="Test Adres"
        )
        self.apartments = [
            Apartment.objects.create(
                complex=self.complex,
                unit_no=f"{i}",
                block="A Blok",
                area_m2=Decimal("100.00"),
            )
            for i in range(1, 4)
        ]
        self.billing_run = BillingRun.objects.create(
            complex=self.complex,
            period_year=2026,
            period_month=1,
            window_start_date=date(2026, 1, 1),
            window_end_date=date(2026, 1, 31),
            total_bill=Decimal("3000.00"),
            total_fixed_amount=Decimal("900.00"),
            total_consumption_amount=Decimal("2100.00"),
            total_area=Decimal("300.00"),
            total_energy=Decimal("1000.0000"),
            run_by=self.user,
        )
        self.lines = [
            ApartmentBillingLine.objects.create(
                billing_run=self.billing_run,
                apartment=apartment,
                energy_consumed=Decimal("333.3333"),
                start_energy_value=Decimal("1000.0000"),
                end_energy_value=Decimal("1333.3333"),
                area_ratio=Decimal("0.333333"),
                energy_ratio=Decimal("0.333333"),
                fixed_share=Decimal("300.00"),
                consumption_share=Decimal("700.00"),
                total_payable=Decimal("1000.00"),
            )
            for apartment in self.apartments
        ]

    def test_generate_invoice_for_line_creates_pdf_file(self) -> None:
        path = generate_invoice_for_line(self.lines[0])
        self.assertTrue(path.exists())
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(5), b"%PDF-")

    def test_generate_invoice_for_line_is_idempotent_no_overwrite(self) -> None:
        first_path = generate_invoice_for_line(self.lines[0])
        first_mtime = first_path.stat().st_mtime_ns

        second_path = generate_invoice_for_line(self.lines[0])

        self.assertEqual(first_path, second_path)
        self.assertEqual(first_path.stat().st_mtime_ns, first_mtime)

    def test_generate_invoices_for_run_creates_one_pdf_per_apartment(self) -> None:
        paths = generate_invoices_for_run(self.billing_run)
        self.assertEqual(len(paths), len(self.apartments))
        for path in paths:
            self.assertTrue(path.exists())

    def test_get_invoice_path_for_apartment(self) -> None:
        path = get_invoice_path_for_apartment(self.billing_run, self.apartments[0].id)
        self.assertTrue(path.exists())
        self.assertIn(self.apartments[0].unit_no, path.name)

    def test_build_zip_for_run_contains_all_pdfs_and_one_excel(self) -> None:
        buffer, filename = build_zip_for_run(self.billing_run)

        self.assertEqual(filename, "2026-01_Faturalar.zip")
        with zipfile.ZipFile(buffer) as archive:
            names = archive.namelist()
            # 3 daire PDF'i + 1 toplu Excel özeti.
            self.assertEqual(len(names), len(self.apartments) + 1)

            pdf_names = [n for n in names if n.endswith(".pdf")]
            excel_names = [n for n in names if n.endswith(".xlsx")]
            self.assertEqual(len(pdf_names), len(self.apartments))
            self.assertEqual(excel_names, ["2026-01_Fatura_Ozeti.xlsx"])

            for name in pdf_names:
                content = archive.read(name)
                self.assertEqual(content[:5], b"%PDF-")

            excel_content = archive.read(excel_names[0])
            self.assertEqual(excel_content[:2], b"PK")

    def test_zip_pdf_entries_use_simplified_daire_names(self) -> None:
        buffer, _ = build_zip_for_run(self.billing_run)
        with zipfile.ZipFile(buffer) as archive:
            names = sorted(n for n in archive.namelist() if n.endswith(".pdf"))
        self.assertEqual(names, ["Daire-001.pdf", "Daire-002.pdf", "Daire-003.pdf"])

    def test_zip_excel_summary_contains_all_apartments_with_correct_totals(self) -> None:
        buffer, _ = build_zip_for_run(self.billing_run)
        with zipfile.ZipFile(buffer) as archive:
            excel_bytes = archive.read("2026-01_Fatura_Ozeti.xlsx")

        workbook = load_workbook(BytesIO(excel_bytes))
        sheet = workbook.active
        self.assertEqual(sheet.max_row, 1 + len(self.apartments))

        unit_nos = [sheet.cell(row=r, column=3).value for r in range(2, sheet.max_row + 1)]
        self.assertEqual(sorted(unit_nos), ["1", "2", "3"])

        blocks = [sheet.cell(row=r, column=2).value for r in range(2, sheet.max_row + 1)]
        self.assertTrue(all(b == "A Blok" for b in blocks))

        totals = [sheet.cell(row=r, column=11).value for r in range(2, sheet.max_row + 1)]
        self.assertEqual(totals, [1000.0, 1000.0, 1000.0])

    def test_build_summary_rows_for_run_matches_persisted_lines(self) -> None:
        rows = build_summary_rows_for_run(self.billing_run)
        self.assertEqual(len(rows), len(self.apartments))
        for row in rows:
            self.assertEqual(row.total_payable, Decimal("1000.00"))
            self.assertEqual(row.energy_consumed, Decimal("333.3333"))
            self.assertEqual(row.block, "A Blok")

    def test_pdf_shows_persisted_line_values(self) -> None:
        """PDF, `ApartmentBillingLine`'daki Sabit/Tüketim/Toplam değerlerini
        olduğu gibi (yeniden hesaplamadan) gösterir."""
        line = self.lines[0]
        path = generate_invoice_for_line(line)
        reader = PdfReader(str(path))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)

        self.assertIn("300,00 TL", text)   # Sabit Gider Payı
        self.assertIn("700,00 TL", text)   # Tüketim Gider Payı
        self.assertIn("1.000,00 TL", text)  # Toplam Ödenecek Tutar

    def test_invoice_files_are_organized_by_year_and_month(self) -> None:
        path = generate_invoice_for_line(self.lines[0])
        self.assertEqual(path.parent.name, "01")
        self.assertEqual(path.parent.parent.name, "2026")

    def test_start_end_energy_values_flow_into_pdf(self) -> None:
        """`ApartmentBillingLine.start_energy_value`/`end_energy_value`
        (kümülatif sayaç mantığı — bkz. billing.services), PDF'in "Sayaç
        Bilgileri" bölümünde İlk/Son Enerji olarak görünmelidir."""
        path = generate_invoice_for_line(self.lines[0])
        reader = PdfReader(str(path))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)

        self.assertIn("Sayaç Bilgileri", text)
        self.assertIn("1000,00", text)
        self.assertIn("1333,33", text)
        self.assertIn("333,33", text)
