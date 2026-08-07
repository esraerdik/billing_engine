"""
calculator.py
-------------
Yönetmeliğe uygun gider paylaşım hesaplamasını yapan servis katmanı.

Tasarım notları (SOLID):
    - SRP: `BillingCalculator` yalnızca hesaplama sorumluluğunu taşır;
      veri modeli `models.py`'dedir, hata tipleri `exceptions.py`'dedir.
    - OCP: Paylaşım stratejisi (`ShareStrategy` protokolü) sabit kod
      değil, enjekte edilen bir bağımlılıktır. Yönetmelik değişirse
      veya farklı bir paylaşım yöntemi (örn. sadece m²'ye göre, veya
      farklı oranlarla) gerekirse, `BillingCalculator`'ı değiştirmeden
      yeni bir strateji sınıfı yazmak yeterlidir.
    - DIP: `BillingCalculator`, somut bir enerji kaynağına değil,
      soyut `Apartment` verisine bağımlıdır. Bu veri ister sabit bir
      liste, ister ileride bir Modbus okuyucusundan gelsin, hesaplama
      katmanı hiç değişmez.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from .constants import CONSUMPTION_SHARE_RATIO, FIXED_SHARE_RATIO
from .exceptions import (
    EmptyApartmentListError,
    NegativeAreaError,
    NegativeBillError,
    NegativeEnergyError,
    ZeroAreaError,
    ZeroTotalAreaError,
    ZeroTotalEnergyError,
)
from .models import Apartment, ApartmentBillingResult, BillingSummary


class ShareRatioProvider(Protocol):
    """Sabit gider ve tüketim gideri oranlarını sağlayan protokol.

    `BillingCalculator`, oranları doğrudan `constants.py`'den okumak
    yerine bu protokole bağımlıdır. İleride yönetmelik değişirse veya
    site yönetimi farklı bir oran seti kullanmak isterse (örn. bazı
    yönetmelik istisnalarında farklı yüzdeler), `constants.py`'yi
    değiştirmeden bu protokolü uygulayan yeni bir sağlayıcı enjekte
    edilebilir; `BillingCalculator` kodu hiç değişmez.
    """

    @property
    def consumption_ratio(self) -> float:
        """Tüketim gideri oranını döndürür (0-1 arası)."""
        ...

    @property
    def fixed_ratio(self) -> float:
        """Sabit gider oranını döndürür (0-1 arası)."""
        ...


@dataclass(frozen=True)
class DefaultShareRatioProvider:
    """Yönetmelikte tanımlı %70 / %30 oranlarını sağlayan varsayılan sınıf."""

    consumption_ratio: float = CONSUMPTION_SHARE_RATIO
    fixed_ratio: float = FIXED_SHARE_RATIO


class BillingCalculator:
    """Merkezi ısıtma gider paylaşımını yönetmeliğe göre hesaplayan sınıf.

    Kullanım:
        >>> calculator = BillingCalculator()
        >>> summary = calculator.calculate(total_bill=45000.0, apartments=[...])

    Bağımlılıklar (`ratio_provider`) constructor üzerinden enjekte
    edilir; bu sayede sınıf test edilebilir ve farklı oran setleriyle
    yeniden kullanılabilir kalır.
    """

    def __init__(self, ratio_provider: ShareRatioProvider | None = None) -> None:
        """BillingCalculator örneği oluşturur.

        Args:
            ratio_provider: Sabit/tüketim gideri oranlarını sağlayan
                nesne. `None` verilirse yönetmelikteki varsayılan
                %70/%30 oranları (`DefaultShareRatioProvider`) kullanılır.
        """
        self._ratio_provider: ShareRatioProvider = (
            ratio_provider or DefaultShareRatioProvider()
        )

    def calculate(
        self,
        total_bill: float,
        apartments: Sequence[Apartment],
    ) -> BillingSummary:
        """Toplam faturayı dairelere yönetmeliğe uygun şekilde paylaştırır.

        Args:
            total_bill: Paylaştırılacak toplam fatura tutarı (TL).
                Negatif olamaz.
            apartments: Hesaplamaya dahil edilecek dairelerin listesi.
                Liste boş olamaz. Hiçbir dairenin alanı SIFIR VEYA
                NEGATİF olamaz (fiziksel olarak anlamsız — muhtemel
                veri girişi hatası). Bir dairenin enerji tüketimi TEK
                BAŞINA sıfır olabilir (örn. boş/kullanılmayan daire) —
                negatif olamaz ama sıfır meşrudur. Ama TÜM dairelerin
                enerjisi BİRLİKTE sıfırsa, bu veri girişi sorunu
                sayılır ve hata fırlatılır (bkz. Raises).

        Returns:
            Tüm dairelerin daire bazlı sonuçlarını içeren `BillingSummary`.

        Raises:
            NegativeBillError: `total_bill` negatifse.
            EmptyApartmentListError: `apartments` boşsa.
            NegativeAreaError: Herhangi bir dairenin `area` değeri negatifse.
            ZeroAreaError: Herhangi bir dairenin `area` değeri sıfırsa.
            NegativeEnergyError: Herhangi bir dairenin `energy` değeri negatifse.
            ZeroTotalAreaError: Toplam alan sıfırsa (pratikte artık
                `ZeroAreaError` bunu daha erken yakalar; bu, ek bir
                güvenlik ağı olarak kalır).
            ZeroTotalEnergyError: TÜM dairelerin toplam enerjisi
                sıfırsa (tek bir dairenin enerjisinin sıfır olması
                bu hatayı FIRLATMAZ — sadece o dairenin tüketim payı
                sıfır olur).
        """
        self._validate(total_bill=total_bill, apartments=apartments)

        total_area = sum(apartment.area for apartment in apartments)
        total_energy = sum(apartment.energy for apartment in apartments)

        total_fixed_amount = total_bill * self._ratio_provider.fixed_ratio
        total_consumption_amount = total_bill * self._ratio_provider.consumption_ratio

        results: list[ApartmentBillingResult] = [
            self._calculate_single(
                apartment=apartment,
                total_area=total_area,
                total_energy=total_energy,
                total_fixed_amount=total_fixed_amount,
                total_consumption_amount=total_consumption_amount,
            )
            for apartment in apartments
        ]

        return BillingSummary(
            total_bill=total_bill,
            total_fixed_amount=total_fixed_amount,
            total_consumption_amount=total_consumption_amount,
            total_area=total_area,
            total_energy=total_energy,
            results=results,
        )

    def _calculate_single(
        self,
        apartment: Apartment,
        total_area: float,
        total_energy: float,
        total_fixed_amount: float,
        total_consumption_amount: float,
    ) -> ApartmentBillingResult:
        """Tek bir daire için oranları ve tutarları hesaplar.

        Yöntemin `private` (alt çizgili) olması: bu adım yalnızca
        `calculate()` akışının bir parçasıdır ve sınıf dışından
        çağrılması beklenmez.
        """
        area_ratio = apartment.area / total_area
        # NOT: `total_energy == 0` durumu artık `_validate` tarafından
        # `ZeroTotalEnergyError` ile daha erken engelleniyor (bkz.
        # orada) — bu satıra o durumda hiç ulaşılmaz, bölme işlemi
        # her zaman güvenlidir.
        energy_ratio = apartment.energy / total_energy

        fixed_share = total_fixed_amount * area_ratio
        consumption_share = total_consumption_amount * energy_ratio
        total_payable = fixed_share + consumption_share

        return ApartmentBillingResult(
            apartment_id=apartment.id,
            area=apartment.area,
            energy=apartment.energy,
            area_ratio=area_ratio,
            energy_ratio=energy_ratio,
            fixed_share=fixed_share,
            consumption_share=consumption_share,
            total_payable=total_payable,
        )

    @staticmethod
    def _validate(total_bill: float, apartments: Sequence[Apartment]) -> None:
        """Girdi verilerini yönetmelik hesaplaması yapılmadan önce doğrular.

        Doğrulama sırası bilinçli seçilmiştir: önce genel/global
        koşullar (fatura, boş liste), sonra daire bazlı koşullar
        (negatif/sıfır alan, negatif enerji), en son da türetilmiş
        toplam koşullar (toplam alan, toplam enerji) kontrol edilir.
        Böylece kullanıcı, anlamlı olan ilk hatayı görür.

        NOT (enerji): Bir dairenin enerjisi tek başına sıfır olabilir
        (boş/kullanılmayan daire — meşru bir durum, hata FIRLATMAZ).
        Ama TÜM dairelerin enerjisi birlikte sıfırsa (`total_energy`),
        bu neredeyse her zaman bir veri girişi sorununu işaret eder
        (kalorimetreler henüz okunmamış/girilmemiş gibi) — kullanıcıyı
        sessizce yanlış bir fatura üretmek yerine uyarmak için hata
        fırlatılır.

        NOT (alan): Enerjinin aksine, bir dairenin alanının TEK
        BAŞINA sıfır olması bile meşru bir iş durumu DEĞİLDİR
        (fiziksel olarak anlamsız) — bu yüzden `area == 0` her zaman
        hata fırlatır, `energy == 0` (tek başına) fırlatmaz.

        Raises:
            NegativeBillError, EmptyApartmentListError, NegativeAreaError,
            ZeroAreaError, NegativeEnergyError, ZeroTotalAreaError,
            ZeroTotalEnergyError
        """
        if total_bill < 0:
            raise NegativeBillError(total_bill)

        if len(apartments) == 0:
            raise EmptyApartmentListError()

        for apartment in apartments:
            if apartment.area < 0:
                raise NegativeAreaError(apartment.id, apartment.area)
            if apartment.area == 0:
                raise ZeroAreaError(apartment.id)
            if apartment.energy < 0:
                raise NegativeEnergyError(apartment.id, apartment.energy)

        # NOT: Yukarıdaki döngü her dairenin alanının > 0 olmasını zaten
        # garanti ettiği için, aşağıdaki toplam alan kontrolü artık
        # normal akışta hiçbir zaman tetiklenmez (pozitif sayıların
        # toplamı her zaman pozitiftir). Kasıtlı olarak KALDIRILMADI —
        # ek bir güvenlik ağı olarak duruyor; `ZeroTotalAreaError`
        # sınıfı da bu yüzden hâlâ tanımlı.
        total_area = sum(apartment.area for apartment in apartments)
        total_energy = sum(apartment.energy for apartment in apartments)

        if total_area == 0:
            raise ZeroTotalAreaError()
        if total_energy == 0:
            raise ZeroTotalEnergyError()
