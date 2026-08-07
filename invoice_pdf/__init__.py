"""Faturalandırma sonuçlarını A4 PDF Gider Bildirimine dönüştüren bağımsız modül.

Bu paket `domain` (hesaplama motoru) ve `billing` (Django ORM/uygulama
katmanı) ile aynı ayrım prensibini izler: PDF üretimi bir GÖRSELLEŞTİRME
katmanıdır, hiçbir hesaplama YAPMAZ. Girdisi zaten hesaplanmış sonuçlardır
(bkz. `invoice_pdf.models.InvoiceData`); tek sorumluluğu bu veriyi
profesyonel görünümlü bir PDF'e dökmektir.

Katmanlar:
    - `models.py`     : Django/ORM'den bağımsız, saf PDF veri modelleri.
    - `formatters.py` : Para/tarih/oran biçimleme yardımcıları (Decimal).
    - `styles.py`      : Renk paleti, yazı tipi kaydı, tablo/paragraf stilleri.
    - `generator.py`  : ReportLab (Platypus) ile PDF üretimi — Django'dan
      habersizdir, yalnızca `InvoiceData` alır.
    - `service.py`    : Django ORM'e bağımlı TEK dosya — `BillingRun`/
      `ApartmentBillingLine`'dan `InvoiceData` inşa eder, dosyayı
      `generated_invoices/<yıl>/<ay>/` altına yazar, toplu ZIP üretir.
"""
