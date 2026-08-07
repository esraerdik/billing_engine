"""
formatting.py
-------------
UI katmanına özgü görüntüleme yardımcıları.

İş mantığı İÇERMEZ — sadece `BillingPeriod` gibi domain nesnelerini
kullanıcıya gösterirken okunabilir Türkçe metne çevirir. Hem
`user_window.py` (ay seçim kutusu) hem `admin_window.py` (bekleyen
talep listesi) aynı ay adı listesini kullanır; burada tek yerde
tutulması, ikisinin birbirinden bağımsız, yanlışlıkla farklı
listeler tutmasını engeller.
"""

from __future__ import annotations

from domain.models import BillingPeriod

TURKISH_MONTH_NAMES: tuple[str, ...] = (
    "Ocak",
    "Şubat",
    "Mart",
    "Nisan",
    "Mayıs",
    "Haziran",
    "Temmuz",
    "Ağustos",
    "Eylül",
    "Ekim",
    "Kasım",
    "Aralık",
)


def format_period(period: BillingPeriod) -> str:
    """Bir `BillingPeriod`'u 'Ağustos 2026' gibi okunabilir metne çevirir."""
    month_name = TURKISH_MONTH_NAMES[period.month - 1]
    return f"{month_name} {period.year}"
