"""
models.py (invoice_pdf)
------------------------
PDF Gider Bildirimi VE toplu Excel özeti (bkz. `excel.py`) için saf veri
modelleri.

Bu dataclass'lar BİLİNÇLİ OLARAK `domain.models` veya `billing.models`'dan
FARKLIDIR ve onlara hiçbir bağımlılığı yoktur:
    - `domain.models` (BillingSummary, ApartmentBillingResult) hesaplama
      motorunun çıktısını temsil eder; PDF'ye özgü hiçbir alan (bildirim
      numarası, apartman adresi, kullanıcı adı vb.) taşımaz ve TAŞIMAMALIDIR
      — bu ayrım "Domain modellerini PDF'ye bağımlı hale getirme" kuralının
      doğal sonucudur.
    - Bu modül yerine yeni bir PDF-özel model seti tanımlayarak, ileride
      PDF şablonu değişse (yeni alan, farklı görünüm) bile `domain` ve
      `billing` katmanlarının hiç etkilenmemesi garanti edilir.

`invoice_pdf.service` (Django/ORM'e bağımlı tek katman), bu dataclass'ları
`billing.models` nesnelerinden inşa eder; `invoice_pdf.generator` ise
SADECE bu dataclass'ları girdi olarak alır — Django'dan tamamen habersizdir.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class InvoiceLineItems:
    """Gider dağılımı tablosundaki kalemler.

    Bu alanların TÜMÜ `invoice_pdf.service` tarafından, persist edilmiş
    `ApartmentBillingLine` kaydından OLDUĞU GİBİ okunur — PDF katmanı
    (`generator.py`) hiçbir hesaplama YAPMAZ.

    Not: Bu tablo eskiden "Ortak Alan Gideri", "Hizmet Bedeli", "Ek Ödeme"
    ve "İndirim" kalemlerini de içeriyordu; bunlar kullanıcı talebiyle
    PDF'den (ne tablo ne toplam) tamamen kaldırıldı.

    Attributes:
        fixed_share: Sabit gider payı (TL) — hesaplama motorundan.
        consumption_share: Tüketim gider payı (TL) — hesaplama motorundan.
        total_payable: Toplam ödenecek tutar (TL) — hesaplama motorundan.
    """

    fixed_share: Decimal
    consumption_share: Decimal
    total_payable: Decimal


@dataclass(frozen=True)
class InvoiceData:
    """Tek bir dairenin PDF Gider Bildirimi için gereken TÜM veriler.

    `invoice_pdf.generator.build_invoice_pdf`'in tek girdisidir. Bu nesne
    inşa edildikten sonra PDF üretimi sırasında hiçbir alan yeniden
    hesaplanmaz/sorgulanmaz — üretici (`generator.py`) salt bir görselleştirme
    katmanıdır.

    Attributes:
        invoice_number: Bildirim numarası (örn. "000001"). Kaynak:
            `ApartmentBillingLine.id` (bkz. `service.py`). Dosya adında
            kullanılır (bkz. `service._invoice_output_path`) ama kullanıcı
            talebiyle PDF İÇERİĞİNDE artık GÖSTERİLMEZ (bkz. `generator.py`
            `_build_header_flowables`) — sadece `issue_date` (Bildirim
            Tarihi) başlıkta yer alır.
        issue_date: Bildirimin oluşturulduğu tarih.
        system_title: Sistem/Firma başlığı (PDF üst bilgisi).
        complex_name: Apartman/site adı.
        complex_address: Apartman/site adresi (boşsa "—").
        unit_no: Daire numarası.
        resident_name: Daire sakini adı (yoksa `None` → "—").
        prepared_by_username: Hesaplamayı çalıştıran kullanıcının adı.
        apartment_area_m2: Dairenin kullanım alanı (m²).
        window_start: Fatura aralığı başlangıç tarihi.
        window_end: Fatura aralığı bitiş tarihi.
        boiler_bill: Kazan faturası (toplam fatura tutarı, TL).
        total_building_area_m2: Binanın toplam kullanım alanı (m²).
        total_building_energy: Binanın toplam enerji tüketimi.
        apartment_count: Bu faturalandırmaya dahil edilen daire sayısı.
        start_energy_value: Bu dairenin İlk Enerji (başlangıç) endeksi —
            kümülatif sayaç mantığıyla uyumlu; Modbus okumasından veya
            kullanıcı panelindeki manuel girişten gelir. Yoksa `None`
            (PDF'de "—" gösterilir).
        end_energy_value: Bu dairenin Son Enerji (bitiş) endeksi. Yoksa
            `None`.
        energy_consumed: Tüketim (`end_energy_value - start_energy_value`).
            Bu fark PDF'de YENİDEN HESAPLANMAZ — `billing.services`'ten
            olduğu gibi aktarılır (bkz. `ApartmentBillingLine.energy_consumed`).
        line_items: Gider dağılımı tablosu kalemleri.
    """

    invoice_number: str
    issue_date: date
    system_title: str
    complex_name: str
    complex_address: str | None
    unit_no: str
    resident_name: str | None
    prepared_by_username: str
    apartment_area_m2: Decimal
    window_start: date
    window_end: date
    boiler_bill: Decimal
    total_building_area_m2: Decimal
    total_building_energy: Decimal
    apartment_count: int
    start_energy_value: Decimal | None
    end_energy_value: Decimal | None
    energy_consumed: Decimal | None
    line_items: InvoiceLineItems


@dataclass(frozen=True)
class ApartmentSummaryRow:
    """Toplu Excel özetinde ("Tüm PDF'leri Oluştur" → ZIP) TEK bir dairenin
    satırı.

    `InvoiceData` ile aynı prensiple, bu satır da `invoice_pdf.service`
    içinde AYNI `ApartmentBillingLine` kaydından inşa edilir — yani PDF ve
    Excel birbirinden bağımsız bir hesaplama yapmaz, ikisi de zaten
    persist edilmiş `BillingSummary` sonuçlarını okur (bkz. `service.py`
    `_build_invoice_data` / `_build_summary_row`).

    Genişletilebilirlik: İleride yeni bir hesaplama kalemi Excel'e sütun
    olarak eklenmek istendiğinde, YALNIZCA bu dataclass'a yeni bir alan
    eklemek ve `excel.py`'deki `_COLUMNS` tablosuna karşılık gelen tek bir
    satır eklemek yeterlidir — `excel.py`'nin geri kalanı (workbook/stil
    oluşturma mantığı) hiç değişmez.

    Attributes:
        complex_name: Apartman/site adı.
        block: Blok adı (opsiyonel, yoksa boş metin → Excel'de "—").
        unit_no: Daire numarası.
        resident_name: Daire sakini/malik adı (yoksa `None` → "—").
        area_m2: Dairenin kullanım alanı (m²).
        start_energy_value: İlk Enerji (başlangıç) endeksi (yoksa `None`).
        end_energy_value: Son Enerji (bitiş) endeksi (yoksa `None`).
        energy_consumed: Tüketim (`end - start`) — burada YENİDEN
            HESAPLANMAZ, `billing.services`'ten olduğu gibi aktarılır.
        fixed_share: Sabit gider payı (TL) — hesaplama motorundan.
        consumption_share: Tüketim gider payı (TL) — hesaplama motorundan.
        total_payable: Toplam ödenecek tutar (TL) — hesaplama motorundan.
    """

    complex_name: str
    block: str
    unit_no: str
    resident_name: str | None
    area_m2: Decimal
    start_energy_value: Decimal | None
    end_energy_value: Decimal | None
    energy_consumed: Decimal | None
    fixed_share: Decimal
    consumption_share: Decimal
    total_payable: Decimal
