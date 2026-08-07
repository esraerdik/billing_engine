"""
history.py
----------
Tamamlanmış faturalandırma çalıştırmalarının dönem (yıl/ay) bazlı arşivi.

Bu dosya "bu dönemde daha önce ne hesaplandı" sorusuna cevap verir —
`authorization.py`'nin sorduğu "bu dönem için kaç kez çalıştırıldı,
izin var mı" sorusundan AYRI bir kaygıdır:
    - `BillingRunAuthorizer` (authorization.py): SAYI tutar — izin
      kontrolü için "kaç kez çalıştırıldı" bilgisi yeterlidir.
    - `BillingHistory` (bu dosya): SONUÇ tutar — "her çalıştırmada
      ne hesaplandı" bilgisinin kendisini saklar.

Bir dönem birden fazla kez çalıştırılmışsa (örn. admin onayıyla
yapılan bir düzeltme), o dönemin TÜM çalıştırma geçmişi saklanır —
yeni bir çalıştırma eskisinin üzerine yazılmaz. `latest_for()` en son
çalıştırmayı, `all_for()` o dönemin tüm geçmişini döndürür.

Mimari not:
    Bu katman da (authorization.py gibi) şu an yalnızca BELLEK
    İÇİNDE tutar; ileride bir veritabanı eklenince `_entries`
    sözlüğü yerini bir repository'ye bırakabilir; dışa açık
    `record`/`latest_for`/`all_for`/`all_entries` imzaları
    değişmeden kalır. `calculator.py` ve `authorization.py` bu
    dosyanın varlığından habersizdir; sadece `UserBillingPanel`
    (authorization.py içinde) bu sınıfı bir bağımlılık olarak alır.
"""

from __future__ import annotations

from datetime import datetime

from .models import BillingHistoryEntry, BillingPeriod, BillingSummary


class BillingHistory:
    """Tamamlanmış tüm faturalandırma çalıştırmalarını dönem bazında arşivler.

    `UserBillingPanel`, her başarılı `run_billing()` çağrısının SONUNDA
    burada bir kayıt bırakır (bkz. authorization.py). `AdminBillingPanel`
    ise aynı örneği salt-okunur olarak sorgulayabilir — ikisi de aynı
    `BillingHistory` nesnesini paylaşarak haberleşir.
    """

    def __init__(self) -> None:
        self._entries: dict[BillingPeriod, list[BillingHistoryEntry]] = {}

    def record(
        self, period: BillingPeriod, summary: BillingSummary
    ) -> BillingHistoryEntry:
        """Tamamlanmış bir çalıştırmayı bu dönemin geçmişine ekler.

        Sadece `BillingCalculator.calculate()` BAŞARIYLA tamamlandıktan
        SONRA çağrılmalıdır — `authorization.py`'deki `record_run` ile
        aynı prensip: başarısız bir deneme geçmişe hiç girmemelidir.

        Returns:
            Oluşturulan `BillingHistoryEntry` (zaman damgası dahil).
        """
        entry = BillingHistoryEntry(
            period=period, summary=summary, recorded_at=datetime.now()
        )
        self._entries.setdefault(period, []).append(entry)
        return entry

    def latest_for(self, period: BillingPeriod) -> BillingHistoryEntry | None:
        """Bu dönem için en son tamamlanan çalıştırmayı döndürür.

        O dönem için hiç kayıt yoksa `None` döner — bu bir hata değil,
        "henüz faturalandırılmamış" anlamına gelen geçerli bir durumdur.
        """
        entries = self._entries.get(period, [])
        return entries[-1] if entries else None

    def all_for(self, period: BillingPeriod) -> list[BillingHistoryEntry]:
        """Bu dönem için TÜM çalıştırma geçmişini kronolojik sırayla döndürür.

        Yeni bir liste döndürülür (iç listenin referansı değil); çağıran
        kod dönen listeyi değiştirse bile `BillingHistory`'nin iç
        durumu bundan etkilenmez.
        """
        return list(self._entries.get(period, []))

    def periods_on_record(self) -> list[BillingPeriod]:
        """Kaydı bulunan tüm dönemleri, yıl/ay sırasına göre döndürür."""
        return sorted(self._entries.keys(), key=lambda p: (p.year, p.month))

    def all_entries(self) -> list[BillingHistoryEntry]:
        """Tüm dönemlerin tüm kayıtlarını, dönem sırasına göre döndürür.

        "Geçmiş faturalar" listesi/raporu istendiğinde tek çağrı
        noktasıdır — örn. bir admin ekranında "tüm geçmiş" görünümü.
        """
        flattened: list[BillingHistoryEntry] = []
        for period in self.periods_on_record():
            flattened.extend(self._entries[period])
        return flattened
