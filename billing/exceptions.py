"""
exceptions.py (billing app)
----------------------------
Fatura tarih aralığı (window) doğrulamasına özgü hatalar.

Bu hatalar `domain.exceptions.BillingEngineError` hiyerarşisinin BİR
PARÇASI DEĞİLDİR — domain katmanı hesaplama girdisiyle (fatura tutarı,
alan, enerji) ilgilenir; bu dosyadaki hatalar ise "bu tarih aralığı
veritabanı geçmişiyle tutarlı mı" sorusuyla ilgilenir, yani tamamen
Django/persistence katmanına ait bir kaygıdır. Bu ayrım bilinçlidir:
domain katmanı (`calculator.py`, `models.py`, ...) tarih aralığı
kavramından habersizdir ve öyle kalmalıdır.
"""

from __future__ import annotations

from datetime import date


class BillingWindowError(Exception):
    """Fatura tarih aralığı doğrulama hatalarının ortak üst sınıfı."""


class InvalidBillingWindowError(BillingWindowError):
    """Başlangıç tarihi bitiş tarihinden sonra olduğunda fırlatılır."""

    def __init__(self, window_start: date, window_end: date) -> None:
        self.window_start = window_start
        self.window_end = window_end
        super().__init__(
            f"Başlangıç tarihi ({window_start:%d.%m.%Y}) bitiş tarihinden "
            f"({window_end:%d.%m.%Y}) sonra olamaz."
        )


class SameBillingWindowDatesError(BillingWindowError):
    """Başlangıç ve bitiş tarihi birbirine eşit olduğunda fırlatılır."""

    def __init__(self, window_date: date) -> None:
        self.window_date = window_date
        super().__init__(
            f"Fatura Aralığı başlangıç ve bitiş tarihi aynı olamaz "
            f"({window_date:%d.%m.%Y})."
        )


class FutureBillingWindowEndError(BillingWindowError):
    """Bitiş tarihi bugünden ileri (gelecekteki) bir tarih olduğunda fırlatılır."""

    def __init__(self, window_end: date, today: date) -> None:
        self.window_end = window_end
        self.today = today
        super().__init__(
            f"Fatura Aralığı bitiş tarihi ({window_end:%d.%m.%Y}) gelecekte "
            f"bir tarih olamaz (bugün: {today:%d.%m.%Y})."
        )


class FutureBillingWindowStartError(BillingWindowError):
    """Başlangıç tarihi bugünden ileri (gelecekteki) bir tarih olduğunda fırlatılır."""

    def __init__(self, window_start: date, today: date) -> None:
        self.window_start = window_start
        self.today = today
        super().__init__(
            f"Fatura Aralığı başlangıç tarihi ({window_start:%d.%m.%Y}) "
            f"gelecekte bir tarih olamaz (bugün: {today:%d.%m.%Y})."
        )


# Not: Tarih aralığı çakışması artık bir HATA DEĞİLDİR. Daha önce burada
# bulunan `OverlappingBillingPeriodError`, seçilen aralık geçmiş bir
# faturalandırmayla (kısmen veya birebir) çakıştığında isteği sert biçimde
# reddediyordu. İş kuralı gereği bu davranış kaldırıldı: her çakışma artık
# bir yeniden faturalandırma TALEBİ (`ApprovalRequest`) oluşturup admin
# onayına yönlendirilir (bkz. billing.services._overlapping_runs_exist ve
# run_billing_or_request_approval). Çakışma tespiti, hata fırlatarak değil,
# `AdminApprovalRequiredError` ile bu akışı tetikleyerek ele alınır.


class ComplexAccessDeniedError(Exception):
    """Bir kullanıcı, erişim yetkisi olmayan bir apartman (`ApartmentComplex`)
    üzerinde işlem (hesaplama çalıştırma vb.) yapmaya çalıştığında
    fırlatılır. Bu kontrol hem `dashboard` view katmanında (kullanıcıya
    sadece yetkili olduğu apartmanlar gösterilir) hem de burada,
    `billing.services` seviyesinde tekrar uygulanır — ikinci kontrol,
    formun/URL'nin manipüle edilip yetkisiz bir `complex_id` gönderilmesi
    ihtimaline karşı bir güvenlik katmanıdır.
    """

    def __init__(self, complex_name: str) -> None:
        self.complex_name = complex_name
        super().__init__(f"“{complex_name}” apartmanına erişim yetkiniz bulunmuyor.")


class InvalidEnergyReadingError(Exception):
    """Bir dairenin "Son Enerji" endeksi "İlk Enerji" endeksinden küçük
    girildiğinde fırlatılır.

    Kümülatif sayaç mantığında (bkz. `billing.services._build_domain_apartments`
    ve ileride gerçek Modbus okumaları) bitiş endeksi hiçbir zaman başlangıç
    endeksinden küçük olamaz — aksi hâlde negatif tüketim ortaya çıkar. Bu
    kontrol, domain katmanındaki genel `NegativeEnergyError`'dan ÖNCE,
    kullanıcıya daha anlaşılır ("hangi daire, hangi iki değer") bir mesaj
    vermek için burada tekrar uygulanır.
    """

    def __init__(self, unit_no: str, start_value: float, end_value: float) -> None:
        self.unit_no = unit_no
        self.start_value = start_value
        self.end_value = end_value
        super().__init__(
            f"“{unit_no}” dairesi için Son Enerji endeksi ({end_value}), "
            f"İlk Enerji endeksinden ({start_value}) küçük olamaz."
        )


class ApartmentInUseError(Exception):
    """Daire silinmek istendiğinde, kendisine bağlı (sayaç, fatura satırı
    vb. `PROTECT` ilişkili) kayıtlar bulunduğu için silme işlemi
    reddedildiğinde fırlatılır.

    Not: `billing.services.delete_apartment`, bu durumda artık kullanıcıya
    sadece bir hata döndürmek yerine daireyi otomatik olarak pasif hale
    getirir (bkz. o fonksiyonun docstring'i) — bu sınıf yine de (örn.
    doğrudan ORM ile silme denenen başka bir çağıran için) kullanılabilir
    durumda tutulur.
    """

    def __init__(self, unit_no: str) -> None:
        self.unit_no = unit_no
        super().__init__(
            f"“{unit_no}” dairesi silinemedi: bu daireyle ilişkili kayıtlar "
            "(sayaç, fatura sonucu vb.) bulunduğu için silme işlemi "
            "yapılamıyor."
        )


class ComplexInUseError(Exception):
    """Bina/site silinmek istendiğinde, kendisine bağlı (daire, fatura
    çalıştırması, onay talebi vb. `PROTECT` ilişkili) kayıtlar bulunduğu
    için silme işlemi reddedildiğinde fırlatılır.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(
            f"“{name}” binası silinemedi: bu binaya bağlı daire/fatura "
            "kayıtları bulunduğu için silme işlemi yapılamıyor. Önce bağlı "
            "daireleri kaldırmanız (veya pasif hale getirmeniz) gerekir."
        )
