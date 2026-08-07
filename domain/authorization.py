"""
authorization.py
-----------------
Faturalandırma ÇALIŞTIRMA iznini yöneten katman.

Bu dosya "hesap doğru mu" sorusuyla ilgilenmez (o `calculator.py`'nin
işi); sadece "bu hesaplamayı ŞİMDİ çalıştırmaya izin var mı" sorusuyla
ilgilenir:
    - Her dönem (ay) için varsayılan olarak `FREE_RUNS_PER_MONTH`
      kadar ücretsiz çalıştırma hakkı vardır (varsayılan: 1).
    - Bu hak tükendikten sonra, aynı dönem için tekrar çalıştırmak
      isteyen kullanıcı, admin onayı olmadan engellenir.
    - Admin onay verdiğinde, bu tek kullanımlık bir haktır: bir sonraki
      çalıştırmayı açar, ondan sonraki tekrar onay ister.

Mimari not:
    Bu katman `BillingCalculator`'ı SARAR (composition), onu
    değiştirmez. `calculator.py` bu dosyanın varlığından habersizdir.
    İleride izin politikası değişse (örn. "ayda 2 ücretsiz hak" gibi),
    `RunPolicyProvider` üzerinden enjekte edilir; `calculator.py`'ye
    hiç dokunulmaz — `ShareRatioProvider` deseniyle birebir aynı fikir.

    `UserBillingPanel` ve `AdminBillingPanel`, ileride eklenecek bir
    UI'nin (PyQt/web) bağlanacağı iki net giriş noktasıdır. Kendileri
    UI DEĞİLDİR — sadece "kullanıcı tarafı ne yapabilir" ve "admin
    tarafı ne yapabilir" sorularını modelleyen düz Python sınıflarıdır.

    Her iki panel de, "geçmişte ne hesaplandı" sorusuna cevap veren
    `BillingHistory` (history.py) nesnesini de paylaşır. `authorize_run`/
    `record_run` "kaç kez çalıştı" sayısını tutar; `BillingHistory` ise
    her çalıştırmanın SONUCUNU dönem bazında arşivler — ikisi ayrı
    kaygılar olduğu için ayrı sınıflardır, ama aynı akışta birlikte
    kullanılırlar (bkz. `UserBillingPanel.run_billing`).

    Durum (kaç kez çalıştırıldı, hangi dönem onaylı) şu an yalnızca
    BELLEK İÇİNDE tutulur — henüz veritabanı yok, bu bilinçli bir
    tercih. İleride bir veritabanı eklenince, `BillingRunAuthorizer`
    içindeki sözlükler yerini bir repository'ye bırakabilir; dışa
    açık metod imzaları (`authorize_run`, `record_run`, `approve`...)
    değişmeden kalabilir.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from .calculator import BillingCalculator
from .constants import FREE_RUNS_PER_MONTH
from .exceptions import AdminApprovalRequiredError
from .history import BillingHistory
from .models import (
    Apartment,
    BillingHistoryEntry,
    BillingPeriod,
    BillingSummary,
)


class RunPolicyProvider(Protocol):
    """Ayda kaç ücretsiz çalıştırma hakkı olduğunu sağlayan protokol.

    `BillingCalculator`'daki `ShareRatioProvider` ile birebir aynı
    mantık: politika sabit kod değil, enjekte edilen bir bağımlılıktır.
    Yönetmelik veya site yönetimi politikası değişirse, bu protokolü
    uygulayan yeni bir sağlayıcı enjekte edilir; `BillingRunAuthorizer`
    kodu hiç değişmez.
    """

    @property
    def free_runs_per_month(self) -> int:
        """Bir dönem için admin onayı gerekmeyen çalıştırma sayısı."""
        ...


@dataclass(frozen=True)
class DefaultRunPolicyProvider:
    """Varsayılan politika: ayda `FREE_RUNS_PER_MONTH` ücretsiz hak."""

    free_runs_per_month: int = FREE_RUNS_PER_MONTH


class BillingRunAuthorizer:
    """Dönem bazlı çalıştırma sayacını ve admin onaylarını tutan servis.

    `UserBillingPanel` ve `AdminBillingPanel` bu sınıfı paylaşarak
    (aynı örneği) haberleşir: kullanıcı tarafı `authorize_run` /
    `record_run` çağırır, admin tarafı `approve` / `deny` /
    `pending_periods` çağırır. İkisi arasındaki tek bağ bu nesnedir —
    birbirlerini doğrudan bilmezler.
    """

    def __init__(self, policy_provider: RunPolicyProvider | None = None) -> None:
        """BillingRunAuthorizer örneği oluşturur.

        Args:
            policy_provider: Aylık ücretsiz hak sayısını sağlayan
                nesne. `None` verilirse varsayılan politika
                (`DefaultRunPolicyProvider`) kullanılır.
        """
        self._policy_provider: RunPolicyProvider = (
            policy_provider or DefaultRunPolicyProvider()
        )
        self._run_counts: dict[BillingPeriod, int] = {}
        self._approved_extra_runs: dict[BillingPeriod, int] = {}
        self._pending_periods: set[BillingPeriod] = set()
        self._pending_requests: list[dict] = []

    def authorize_run(self, period: BillingPeriod) -> None:
        """Bu dönem için ŞİMDİ bir çalıştırma başlatılabilir mi kontrol eder.

        Durumu DEĞİŞTİRMEZ — salt okunur bir kontroldür. Onay/sayaç
        tüketimi yalnızca `record_run` başarıyla çağrıldığında
        gerçekleşir. Bu ayrım bilinçlidir: `authorize_run` geçse ama
        `record_run`'a hiç ulaşılmadan hesaplama hata verirse (örn.
        geçersiz daire verisi), tüketilmemiş bir admin onayı ya da
        ücretsiz hak kaybolmaz.

        Raises:
            AdminApprovalRequiredError: Ücretsiz hak tükenmiş ve bu
                dönem için kullanılmamış bir admin onayı yoksa.
        """
        runs_so_far = self._run_counts.get(period, 0)
        if runs_so_far < self._policy_provider.free_runs_per_month:
            return  # ücretsiz haklardan biri kullanılıyor

        if self._approved_extra_runs.get(period, 0) <= 0:

            self._pending_periods.add(period)

            if not any(r["period"] == period for r in self._pending_requests):
                self._pending_requests.append({
                    "username": "user",
                    "period": period,
                })

            raise AdminApprovalRequiredError(period)
        # approved_extra_runs > 0: onay var, izinli — tüketim record_run'da

    def record_run(self, period: BillingPeriod) -> None:
        """Başarıyla TAMAMLANMIŞ bir çalıştırmayı kaydeder.

        Yalnızca `BillingCalculator.calculate()` hatasız tamamlandıktan
        SONRA çağrılmalıdır (bkz. `UserBillingPanel.run_billing`).
        Eğer bu çalıştırma ücretsiz hakkı aşıyorsa, kullanılan admin
        onayını da bir birim düşürür.
        """
        runs_so_far = self._run_counts.get(period, 0)
        if runs_so_far >= self._policy_provider.free_runs_per_month:
            self._approved_extra_runs[period] = max(
                0, self._approved_extra_runs.get(period, 0) - 1
            )
            self._pending_periods.discard(period)
        self._run_counts[period] = runs_so_far + 1

    def approve(self, period: BillingPeriod) -> None:
        """Admin, belirtilen dönem için bir (1) ek çalıştırma hakkı verir.

        Bu, tek kullanımlık bir haktır: `record_run` onu tükettiğinde
        bir sonraki çalıştırma tekrar onay ister. Admin, kullanıcı
        hiç talep etmeden de önceden onay verebilir — bu metod bir
        `pending` talebin var olmasını şart koşmaz.
        """
        self._approved_extra_runs[period] = (
            self._approved_extra_runs.get(period, 0) + 1
        )
        self._pending_periods.discard(period)

    def deny(self, period: BillingPeriod) -> None:
        """Admin, bekleyen bir talebi reddeder; ek hak verilmez."""
        self._pending_periods.discard(period)

    def pending_periods(self) -> list[BillingPeriod]:
        """Şu an admin onayı bekleyen tüm dönemleri döndürür."""
        return sorted(self._pending_periods, key=lambda p: (p.year, p.month))

    def runs_this_period(self, period: BillingPeriod) -> int:
        """Belirtilen dönem için şimdiye kadar kaç çalıştırma tamamlandığını döndürür."""
        return self._run_counts.get(period, 0)

    def pending_requests(self):
        return self._pending_requests


    def approve_request(self, index: int):

        request = self._pending_requests.pop(index)

        self.approve(request["period"])

    def reject_request(self, index: int):

       request = self._pending_requests.pop(index)

       self.deny(request["period"])


class UserBillingPanel:
    """Kullanıcı (site yönetimi/muhasebe) tarafının giriş noktası.

    İleride bir UI (PyQt, web) buraya bağlanacaktır: kullanıcı
    ekranındaki "Faturalandır" butonu bu sınıfın `run_billing`
    metodunu çağıracaktır. Kendisi hiçbir ekran/pencere kodu içermez.
    """

    def __init__(
        self,
        calculator: BillingCalculator,
        authorizer: BillingRunAuthorizer,
        history: BillingHistory,
    ) -> None:
        """UserBillingPanel örneği oluşturur.

        `authorizer` ve `history`, `AdminBillingPanel` ile de
        PAYLAŞILMASI gereken örneklerdir (bkz. `main.py`) — her panel
        kendi başına yeni bir örnek oluşturursa, iki panel birbirinin
        durumunu hiç göremez. Bu yüzden burada varsayılan değer YOKTUR;
        çağıran kod paylaşılan örnekleri açıkça vermek zorundadır.
        """
        self._calculator = calculator
        self._authorizer = authorizer
        self._history = history

    def run_billing(
        self,
        period: BillingPeriod,
        total_bill: float,
        apartments: Sequence[Apartment],
    ) -> BillingSummary:
        """Belirtilen dönem için faturalandırmayı çalıştırır.

        Akış: önce izin kontrolü, sonra hesaplama, sonra çalıştırma
        kaydı, en son geçmişe arşivleme. Bu sıra bilinçlidir — bkz.
        `authorize_run` ve `record_run` docstring'leri: hesaplama
        sırasında hata olursa (`record_run` ve `history.record`
        hiç çağrılmaz), hak/onay tüketilmez VE geçmişe hiçbir kayıt
        girmez (yarım/başarısız bir çalıştırma "geçmiş fatura"
        sayılmamalıdır).

        Raises:
            AdminApprovalRequiredError: Bu dönem için ücretsiz hak
                tükenmiş ve admin onayı verilmemişse. Bu durumda
                `calculate()` hiç ÇAĞRILMAZ.
            BillingEngineError: Hesaplama sırasında geçersiz veri
                bulunursa (örn. negatif alan, boş daire listesi).
        """
        self._authorizer.authorize_run(period)
        summary = self._calculator.calculate(
            total_bill=total_bill, apartments=apartments
        )
        self._authorizer.record_run(period)
        self._history.record(period, summary)
        return summary

    def history_for(self, period: BillingPeriod) -> list[BillingHistoryEntry]:
        """Belirtilen dönemin geçmiş çalıştırma kayıtlarını döndürür.

        Kullanıcı tarafının "bu ay için daha önce ne hesaplanmıştı"
        diye bakabileceği sorgu noktasıdır.
        """
        return self._history.all_for(period)


class AdminBillingPanel:
    """Admin tarafının giriş noktası — onay/red ve bekleyen talepleri görme.

    `UserBillingPanel` ile aynı `BillingRunAuthorizer` ve
    `BillingHistory` örneklerini paylaşarak haberleşir; ikisi
    birbirini doğrudan çağırmaz.
    """

    def __init__(
        self,
        authorizer: BillingRunAuthorizer,
        history: BillingHistory,
    ) -> None:
        self._authorizer = authorizer
        self._history = history

    def pending_periods(self) -> list[BillingPeriod]:
        """Onay bekleyen tüm dönemleri döndürür."""
        return self._authorizer.pending_periods()

    def approve(self, period: BillingPeriod) -> None:
        """Belirtilen dönem için bir ek çalıştırma hakkı onaylar."""
        self._authorizer.approve(period)

    def deny(self, period: BillingPeriod) -> None:
        """Belirtilen dönem için bekleyen talebi reddeder."""
        self._authorizer.deny(period)

    def history_for(self, period: BillingPeriod) -> list[BillingHistoryEntry]:
        """Belirtilen dönemin TÜM geçmiş çalıştırma kayıtlarını döndürür.

        Admin, bir onay talebini değerlendirirken "bu dönem daha önce
        kaç kez ve hangi tutarlarla çalıştırılmış" diye bakabilir.
        """
        return self._history.all_for(period)

    def all_history(self) -> list[BillingHistoryEntry]:
        """Sistemdeki TÜM dönemlerin tüm geçmiş kayıtlarını döndürür.

        Bir admin ekranında "tüm geçmiş faturalar" görünümü için
        tek çağrı noktasıdır.
        """
        return self._history.all_entries()

