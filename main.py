"""
main.py
-------
Örnek kullanım / manuel çalıştırma girişi.

Bu dosya YALNIZCA örnektir: gerçek entegrasyonlarda (Modbus okuyucusu,
UI, API) `BillingCalculator` doğrudan çağrılır; ekrana yazdırma
mantığı burada tutulur, hesaplama motörüne karışmaz.
"""

from __future__ import annotations

from domain.authorization import (
    AdminBillingPanel,
    BillingRunAuthorizer,
    UserBillingPanel,
)
from domain.calculator import BillingCalculator
from domain.exceptions import AdminApprovalRequiredError, BillingEngineError
from domain.history import BillingHistory
from domain.models import (
    Apartment,
    BillingHistoryEntry,
    BillingPeriod,
    BillingSummary,
)


def build_sample_apartments() -> list[Apartment]:
    """Örnek daire verilerini `Apartment` nesnelerine çevirir.

    Gerçek sistemde bu fonksiyonun yerini, ileride Modbus'tan okunan
    kalorimetre verisini `Apartment` nesnelerine dönüştüren bir
    adaptör/repository katmanı alacaktır; `BillingCalculator` bu
    değişiklikten etkilenmez.
    """
    raw_apartments = [
        {"id": 1, "area": 120, "energy": 1250},
        {"id": 2, "area": 95, "energy": 980},
        {"id": 3, "area": 140, "energy": 1540},
        {"id": 4, "area": 110, "energy": 1120},
    ]
    return [
        Apartment(id=item["id"], area=item["area"], energy=item["energy"])
        for item in raw_apartments
    ]


def prompt_for_total_bill() -> float:
    """Toplam fatura tutarını konsoldan okuyup `float`'a çevirir.

    Kullanıcı sayı olarak yorumlanamayan bir metin girerse (örn. "abc"),
    `ValueError` fırlatmak yerine kullanıcıya tekrar sorar; böylece
    program çirkin bir traceback ile durmak yerine kullanıcı doğru
    bir değer girene kadar bekler.

    Negatif değer kontrolü burada YAPILMAZ — bu, `BillingCalculator`ın
    sorumluluğundadır (`NegativeBillError`). Girdi katmanı sadece
    "bu bir sayı mı" sorusuna cevap verir; "bu sayı iş kuralına uygun
    mu" sorusunu hesaplama motörüne bırakır.
    """
    while True:
        raw_input = input("Toplam fatura tutarını girin (TL): ").strip()
        try:
            return float(raw_input)
        except ValueError:
            print(f"  '{raw_input}' geçerli bir sayı değil. Lütfen tekrar deneyin.")


def print_summary(summary: BillingSummary) -> None:
    """Bir `BillingSummary` nesnesini okunabilir biçimde ekrana yazdırır.

    Bu fonksiyon yalnızca gösterim amaçlıdır; hesaplama motörünün
    döndürdüğü nesnelere hiçbir müdahalede bulunmaz.
    """
    print("=" * 72)
    print("MERKEZİ ISITMA GİDER PAYLAŞIM RAPORU")
    print("=" * 72)
    print(f"Toplam Fatura            : {summary.total_bill:,.2f} TL")
    print(f"  Sabit Gider Havuzu     : {summary.total_fixed_amount:,.2f} TL")
    print(f"  Tüketim Gideri Havuzu  : {summary.total_consumption_amount:,.2f} TL")
    print(f"Toplam Alan               : {summary.total_area:,.2f} m²")
    print(f"Toplam Enerji Tüketimi    : {summary.total_energy:,.2f}")
    print("-" * 72)

    for result in summary.results:
        rounded = result.rounded()
        print(f"Daire No               : {rounded.apartment_id}")
        print(f"  Alan (m²)             : {rounded.area}")
        print(f"  Enerji Tüketimi       : {rounded.energy}")
        print(f"  Alan Oranı            : {rounded.area_ratio:.4%}")
        print(f"  Enerji Oranı          : {rounded.energy_ratio:.4%}")
        print(f"  Sabit Gider           : {rounded.fixed_share:,.2f} TL")
        print(f"  Tüketim Gideri        : {rounded.consumption_share:,.2f} TL")
        print(f"  Toplam Ödenecek Tutar : {rounded.total_payable:,.2f} TL")
        print("-" * 72)

    print(f"Kontrol Toplamı (paylar): {summary.sum_of_payables():,.2f} TL")
    print("=" * 72)


def print_history(entries: list[BillingHistoryEntry]) -> None:
    """Bir dönemin geçmiş çalıştırma kayıtlarını okunabilir biçimde yazdırır.

    Bu fonksiyon da `print_summary` gibi yalnızca gösterim amaçlıdır;
    `BillingHistory`'nin döndürdüğü nesnelere hiçbir müdahalede
    bulunmaz.
    """
    if not entries:
        print("  (bu dönem için henüz kayıt yok)")
        return

    for index, entry in enumerate(entries, start=1):
        timestamp = entry.recorded_at.strftime("%Y-%m-%d %H:%M:%S")
        print(
            f"  {index}. çalıştırma - {timestamp} - "
            f"Toplam Fatura: {entry.summary.total_bill:,.2f} TL"
        )


def main() -> None:
    """Kullanıcı ve admin panellerini örnekleyen akışı çalıştırır.

    Akış:
        1) Kullanıcı bu ay için ilk kez faturalandırma çalıştırır —
           ücretsiz hak sayesinde otomatik izin verilir.
        2) Kullanıcı AYNI ay için tekrar çalıştırmayı dener — admin
           onayı olmadan `AdminApprovalRequiredError` fırlatılır.
        3) Admin paneli üzerinden onay verilir.
        4) Kullanıcı tekrar dener — bu kez başarılı olur.

    `authorizer` ve `history`, tek bir örnek olarak oluşturulup her
    iki panele de verilir; gerçek sistemde bu örnekler uygulama
    boyunca (örn. bir web sunucusu sürecinde) canlı tutulur — burada
    tek çalıştırmalık bir demodur.
    """
    total_bill = prompt_for_total_bill()
    apartments = build_sample_apartments()
    period = BillingPeriod.current()

    authorizer = BillingRunAuthorizer()
    history = BillingHistory()
    user_panel = UserBillingPanel(
        calculator=BillingCalculator(), authorizer=authorizer, history=history
    )
    admin_panel = AdminBillingPanel(authorizer=authorizer, history=history)

    print(f"\n[Kullanıcı Paneli] {period} için 1. çalıştırma deneniyor...")
    try:
        summary = user_panel.run_billing(period, total_bill, apartments)
    except BillingEngineError as error:
        print(f"Hesaplama hatası: {error}")
        return
    print("  -> Ücretsiz hak ile otomatik izin verildi.")
    print_summary(summary)

    print(f"\n[Kullanıcı Paneli] {period} için 2. çalıştırma deneniyor (admin onayı olmadan)...")
    try:
        user_panel.run_billing(period, total_bill, apartments)
    except AdminApprovalRequiredError as error:
        print(f"  -> Beklenen sonuç: {error}")

    pending = ", ".join(str(p) for p in admin_panel.pending_periods())
    print(f"\n[Admin Paneli] Onay bekleyen dönemler: {pending}")
    admin_panel.approve(period)
    print(f"  -> {period} dönemi onaylandı.")

    print(f"\n[Kullanıcı Paneli] {period} için 2. çalıştırma tekrar deneniyor (onay sonrası)...")
    try:
        summary_after_approval = user_panel.run_billing(period, total_bill, apartments)
    except BillingEngineError as error:
        print(f"Hesaplama hatası: {error}")
        return
    print("  -> Admin onayıyla izin verildi.")
    print_summary(summary_after_approval)

    print(f"\n[Geçmiş] {period} dönemi için kayıtlı tüm çalıştırmalar:")
    print_history(user_panel.history_for(period))


if __name__ == "__main__":
    main()
