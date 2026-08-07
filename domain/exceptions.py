"""
exceptions.py
-------------
Faturalandırma motörüne özgü, anlamlı hata sınıfları.

Genel `ValueError` yerine bu sınıfların kullanılması; çağıran kodun
(ileride UI, Modbus okuma katmanı veya API) hangi iş kuralının ihlal
edildiğini `except` bloklarında tip bazlı ayırt edebilmesini sağlar.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Sadece tip kontrolü (mypy/IDE) için; çalışma zamanında hiç
    # çalıştırılmaz. Bu sayede models.py <-> exceptions.py arasında
    # döngüsel import oluşmaz (models.py da bu dosyadan
    # InvalidBillingPeriodError'ı import ediyor).
    from .models import BillingPeriod


class BillingEngineError(Exception):
    """Faturalandırma motöründeki tüm özel hataların ortak temel sınıfı.

    Çağıran kod, tek bir `except BillingEngineError:` bloğuyla motöre
    özgü tüm hataları yakalayabilir; spesifik hata tipleri ise ayrı
    ayrı da yakalanabilir.
    """


class NegativeBillError(BillingEngineError):
    """Toplam fatura tutarı negatif olduğunda fırlatılır."""

    def __init__(self, total_bill: float) -> None:
        self.total_bill = total_bill
        super().__init__(
            f"Toplam fatura tutarı negatif olamaz: {total_bill}"
        )


class NegativeEnergyError(BillingEngineError):
    """Bir dairenin kalorimetre enerji tüketimi negatif olduğunda fırlatılır."""

    def __init__(self, apartment_id: int, energy: float) -> None:
        self.apartment_id = apartment_id
        self.energy = energy
        super().__init__(
            f"Daire {apartment_id}: enerji tüketimi negatif olamaz: {energy}"
        )


class NegativeAreaError(BillingEngineError):
    """Bir dairenin kullanım alanı (m²) negatif olduğunda fırlatılır."""

    def __init__(self, apartment_id: int, area: float) -> None:
        self.apartment_id = apartment_id
        self.area = area
        super().__init__(
            f"Daire {apartment_id}: kullanım alanı negatif olamaz: {area}"
        )


class ZeroAreaError(BillingEngineError):
    """Bir dairenin kullanım alanı (m²) sıfır olduğunda fırlatılır.

    Enerji tüketiminin sıfır olması (boş/kullanılmayan daire) meşru
    bir iş durumudur — bu yüzden `calculate()` artık onu engellemiyor.
    Ama bir dairenin ALANININ sıfır olması fiziksel olarak anlamsızdır
    (var olan hiçbir daire 0 m² değildir); bu neredeyse her zaman bir
    veri girişi hatasını işaret eder (alan hiç girilmemiş/unutulmuş).
    Bu yüzden alan ve enerji için sıfır değeri KASITLI OLARAK farklı
    ele alınır: enerji=0 kabul edilir, alan=0 reddedilir.
    """

    def __init__(self, apartment_id: int) -> None:
        self.apartment_id = apartment_id
        super().__init__(
            f"Daire {apartment_id}: kullanım alanı sıfır olamaz — alan girilmemiş olabilir."
        )


class ZeroTotalEnergyError(BillingEngineError):
    """Tüm dairelerin toplam enerji tüketimi (birlikte) sıfır olduğunda
    fırlatılır.

    Bir dairenin TEK BAŞINA enerjisi sıfır olması meşru bir durumdur
    (boş/kullanılmayan daire) ve bu hatayı FIRLATMAZ — sadece o
    dairenin tüketim payı sıfır olur. Ama TÜM dairelerin enerjisi
    BİRLİKTE sıfırsa, bu neredeyse her zaman bir veri girişi sorununu
    işaret eder (kalorimetreler henüz okunmamış/girilmemiş gibi);
    kullanıcıyı sessizce eksik/yanlış bir fatura üretmek yerine
    açıkça uyarmak için hata fırlatılır.
    """

    def __init__(self) -> None:
        super().__init__(
            "Toplam enerji tüketimi sıfır: tüketim gideri paylaştırılamaz."
        )


class ZeroTotalAreaError(BillingEngineError):
    """Tüm dairelerin toplam kullanım alanı sıfır olduğunda fırlatılır.

    Sabit gider (%30), dairelerin toplam alana oranına göre
    paylaştırıldığından, toplam alan sıfırsa bu oran matematiksel
    olarak tanımsızdır (0/0).
    """

    def __init__(self) -> None:
        super().__init__(
            "Toplam kullanım alanı sıfır: sabit gider paylaştırılamaz."
        )


class EmptyApartmentListError(BillingEngineError):
    """Hesaplama için hiçbir daire verisi verilmediğinde fırlatılır."""

    def __init__(self) -> None:
        super().__init__(
            "Daire listesi boş: hesaplama yapılabilecek daire bulunamadı."
        )


class AuthorizationError(BillingEngineError):
    """Faturalandırma ÇALIŞTIRMA izniyle ilgili hataların ortak üst sınıfı.

    Yukarıdaki hatalar "girdi verisi geçerli mi" sorusuna cevap verir;
    bu sınıf ve alt sınıfları ise "bu hesaplamayı şimdi çalıştırmaya
    izin var mı" sorusuna cevap verir. İkisi ayrı kaygılar olduğu için
    ayrı bir alt hiyerarşi olarak tanımlanmıştır, ama hâlâ aynı ortak
    `BillingEngineError` kökünden gelir — çağıran kod istersen tek bir
    `except BillingEngineError:` ile hepsini yakalayabilir.
    """


class AdminApprovalRequiredError(AuthorizationError):
    """Bir dönem için ücretsiz çalıştırma hakkı tükenmişken, admin onayı
    olmadan tekrar çalıştırma denendiğinde fırlatılır.
    """

    def __init__(self, period: "BillingPeriod") -> None:
        self.period = period
        super().__init__(
            f"{period} dönemi için faturalandırma hakkı "
            f"kullanıldı; devam etmek için admin onayı gerekiyor."
        )


class InvalidBillingPeriodError(BillingEngineError):
    """Geçersiz bir ay/yıl değeriyle `BillingPeriod` oluşturulmaya
    çalışıldığında fırlatılır (ay değeri 1-12 aralığının dışındaysa).
    """

    def __init__(self, year: int, month: int) -> None:
        self.year = year
        self.month = month
        super().__init__(
            f"Geçersiz dönem: yıl={year}, ay={month} "
            f"(ay değeri 1-12 arasında olmalıdır)"
        )
