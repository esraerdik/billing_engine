"""
models.py
---------
Faturalandırma motörünün veri modelleri.

Bu modül yalnızca VERİ taşır; iş kuralı / hesaplama mantığı burada
YOKTUR (Single Responsibility). Hesaplama `calculator.py` içindedir.
Bu ayrım sayesinde ileride Modbus'tan okunan canlı enerji verisi,
veya bir UI/DB katmanı, bu sınıfları değiştirmeden üretebilir/tüketebilir.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .constants import CURRENCY_DECIMAL_PLACES, RATIO_DECIMAL_PLACES
from .exceptions import InvalidBillingPeriodError


@dataclass(frozen=True)
class Apartment:
    """Bir bağımsız bölümün (dairenin) ham girdi verisi.

    `frozen=True` seçilmiştir: bir daire kaydı hesaplamaya girdikten
    sonra yanlışlıkla değiştirilemesin diye. Enerji verisi Modbus'tan
    güncel okunduğunda, mevcut nesne mutasyona uğratılmaz; her okuma
    için yeni bir `Apartment` nesnesi üretilir — bu da veri akışını
    öngörülebilir kılar.

    Attributes:
        id: Daire numarası (bağımsız bölüm no).
        area: Kullanım alanı (m²). Negatif olamaz.
        energy: Kalorimetreden okunan enerji tüketim değeri
            (örn. kWh veya ısı ölçer birimi). Negatif olamaz.
    """

    id: int
    area: float
    energy: float


@dataclass(frozen=True)
class ApartmentBillingResult:
    """Bir daire için hesaplanmış nihai faturalandırma sonucu.

    Yönetmeliğin öngördüğü tüm kalemleri (sabit gider, tüketim gideri,
    toplam tutar) ve şeffaflık için kullanılan ara oranları (alan oranı,
    enerji oranı) tek bir nesnede toplar. `frozen=True`: bir sonuç
    üretildikten sonra değiştirilemez; denetim/rapor amaçlı güvenilir
    bir kayıt olarak kalır.

    Attributes:
        apartment_id: Daire numarası.
        area: Dairenin kullanım alanı (m²).
        energy: Dairenin kalorimetre enerji tüketimi.
        area_ratio: Dairenin toplam alan içindeki payı (0-1 arası).
        energy_ratio: Dairenin toplam tüketim içindeki payı (0-1 arası).
        fixed_share: Sabit gider payı (TL).
        consumption_share: Tüketim gideri payı (TL).
        total_payable: Toplam ödenecek tutar (TL).
    """

    apartment_id: int
    area: float
    energy: float
    area_ratio: float
    energy_ratio: float
    fixed_share: float
    consumption_share: float
    total_payable: float

    def rounded(
        self,
        currency_decimals: int = CURRENCY_DECIMAL_PLACES,
        ratio_decimals: int = RATIO_DECIMAL_PLACES,
    ) -> "ApartmentBillingResult":
        """Parasal ve oransal alanları yuvarlanmış yeni bir kopyasını döndürür.

        Sonuç nesnesi `frozen` olduğundan mevcut nesne değiştirilmez;
        raporlama/gösterim için yeni bir nesne üretilir. İç hesaplamalar
        (toplam kontrolü gibi) her zaman yuvarlanmamış değerler üzerinden
        yapılmalıdır; bu metod sadece son kullanıcıya sunum amaçlıdır.

        Args:
            currency_decimals: Parasal alanlar için ondalık basamak sayısı.
            ratio_decimals: Oran alanları için ondalık basamak sayısı.

        Returns:
            Yuvarlanmış değerlere sahip yeni bir `ApartmentBillingResult`.
        """
        return ApartmentBillingResult(
            apartment_id=self.apartment_id,
            area=self.area,
            energy=self.energy,
            area_ratio=round(self.area_ratio, ratio_decimals),
            energy_ratio=round(self.energy_ratio, ratio_decimals),
            fixed_share=round(self.fixed_share, currency_decimals),
            consumption_share=round(self.consumption_share, currency_decimals),
            total_payable=round(self.total_payable, currency_decimals),
        )


@dataclass(frozen=True)
class BillingSummary:
    """Bir faturalandırma çalıştırmasının tüm dairelere ait toplu sonucu.

    Tek tek daire sonuçlarının yanı sıra, doğrulama ve raporlama için
    faydalı toplam değerleri de taşır.

    Attributes:
        total_bill: Girdi olarak verilen toplam fatura tutarı.
        total_fixed_amount: Sabit gider havuzu (total_bill'in %30'u).
        total_consumption_amount: Tüketim gideri havuzu (total_bill'in %70'i).
        total_area: Tüm dairelerin toplam kullanım alanı.
        total_energy: Tüm dairelerin toplam enerji tüketimi.
        results: Daire bazlı sonuçların listesi.
    """

    total_bill: float
    total_fixed_amount: float
    total_consumption_amount: float
    total_area: float
    total_energy: float
    results: list[ApartmentBillingResult]

    def sum_of_payables(self) -> float:
        """Tüm dairelerin ödeyeceği tutarların toplamını döndürür.

        Bu değer `total_bill` ile (kayan nokta hassasiyeti payı hariç)
        eşit olmalıdır; testlerde ve denetimde tutarlılık kontrolü
        için kullanılır.
        """
        return sum(result.total_payable for result in self.results)


@dataclass(frozen=True)
class BillingPeriod:
    """Bir faturalandırma çalıştırmasının ait olduğu ay/yıl.

    Aylık çalıştırma sınırlaması (`authorization.py`) bu değeri
    anahtar olarak kullanır: "2026-08" gibi bir dönem için kaç kez
    çalıştırma yapıldığı ve hangi ek çalıştırmaların onaylandığı ayrı
    ayrı takip edilir.

    `frozen=True` olması sadece "değiştirilemez" anlamına gelmez;
    aynı zamanda nesneyi hashable yapar (dataclass, frozen+eq
    olduğunda otomatik `__hash__` üretir). Bu sayede `BillingPeriod`
    doğrudan bir dict/set anahtarı olarak kullanılabilir — ayrıca bir
    string anahtara ("2026-08") çevirmeye gerek kalmaz.

    Attributes:
        year: Dönemin yılı (örn. 2026).
        month: Dönemin ayı (1-12 arası).
    """

    year: int
    month: int

    def __post_init__(self) -> None:
        if not (1 <= self.month <= 12):
            raise InvalidBillingPeriodError(self.year, self.month)

    @classmethod
    def current(cls) -> "BillingPeriod":
        """Sistem tarihine göre şu anki (yıl, ay) dönemini döndürür.

        Bu metod yalnızca gerçek kullanım noktalarında (örn. `main.py`)
        çağrılmalıdır. `BillingRunAuthorizer` ve testler her zaman
        açık bir `BillingPeriod` nesnesi alır, `current()`'ı kendi
        içinde ÇAĞIRMAZ — bu, iznin sistem saatine gizlice bağımlı
        olmaması ve deterministik test edilebilmesi için önemlidir.
        """
        now = datetime.now()
        return cls(year=now.year, month=now.month)

    def __str__(self) -> str:
        return f"{self.year}-{self.month:02d}"


@dataclass(frozen=True)
class BillingHistoryEntry:
    """Bir dönem için tamamlanmış TEK BİR çalıştırmanın arşiv kaydı.

    `history.py`'deki `BillingHistory`, her başarılı çalıştırma için
    bu nesneden bir tane oluşturup dönem başına bir listede saklar.
    Zaman damgası (`recorded_at`) burada bilinçli olarak dışarıdan
    verilir (nesnenin kendisi `datetime.now()` ÇAĞIRMAZ) — böylece bu
    sınıf, `BillingPeriod` ile aynı prensiple, tamamen deterministik
    ve test edilebilir kalır; sistem saatine bağımlılık yalnızca
    `BillingHistory.record()` içinde, tek bir noktada yaşar.

    Attributes:
        period: Bu kaydın ait olduğu dönem (yıl/ay).
        summary: O çalıştırmanın ürettiği tam sonuç.
        recorded_at: Bu kaydın oluşturulduğu an (denetim/sıralama için).
    """

    period: BillingPeriod
    summary: BillingSummary
    recorded_at: datetime
