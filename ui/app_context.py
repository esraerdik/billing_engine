"""
app_context.py
---------------
Uygulama ömrü boyunca PAYLAŞILMASI gereken iş mantığı örneklerini
BİR KEZ oluşturup bir arada tutar.

`UserBillingPanel` ve `AdminBillingPanel`, `BillingRunAuthorizer` ve
`BillingHistory`'yi PAYLAŞILAN örnekler olarak bekler (bkz.
authorization.py, docstring'deki "varsayılan değer YOKTUR" notu) —
her pencere kendi başına yeni bir örnek oluşturursa, kullanıcı
tarafında yapılan bir çalıştırma admin tarafında hiç görünmez.

Bu yüzden `authorizer`, `history` ve `calculator` burada, uygulama
başlarken TEK SEFER oluşturulur. Login ekranından hangi role
girilirse girilsin (kullanıcı çıkış yapıp aynı uygulama açıkken
tekrar admin olarak girse bile), hep AYNI örnekler kullanılır.

Bu dosya iş mantığına hiçbir şey EKLEMEZ, DEĞİŞTİRMEZ — yalnızca
mevcut `BillingCalculator`, `BillingRunAuthorizer`, `BillingHistory`,
`UserBillingPanel`, `AdminBillingPanel` sınıflarını olduğu gibi
çağırıp birbirine bağlar.
"""

from __future__ import annotations

from dataclasses import dataclass

from domain.authorization import (
    AdminBillingPanel,
    BillingRunAuthorizer,
    UserBillingPanel,
)
from domain.calculator import BillingCalculator
from domain.history import BillingHistory


@dataclass
class AppContext:
    """UI'nin ihtiyaç duyduğu, önceden kurulmuş panel örneklerini taşır.

    Pencereler (`UserWindow`, `AdminWindow`) bu nesneyi alır, içindeki
    `user_panel`/`admin_panel`'i kullanır — `BillingCalculator`,
    `BillingRunAuthorizer`, `BillingHistory`'yi doğrudan hiç görmez.
    """

    user_panel: UserBillingPanel
    admin_panel: AdminBillingPanel


def build_app_context() -> AppContext:
    """Paylaşılan iş mantığı örneklerini oluşturup panellere sarar.

    `gui_main.py` tarafından uygulama başlarken TEK SEFER çağrılır;
    dönen `AppContext`, `LoginWindow` üzerinden hangi pencere
    açılırsa açılsın aynı örneği taşır.
    """
    authorizer = BillingRunAuthorizer()
    history = BillingHistory()
    calculator = BillingCalculator()

    user_panel = UserBillingPanel(
        calculator=calculator, authorizer=authorizer, history=history
    )
    admin_panel = AdminBillingPanel(authorizer=authorizer, history=history)

    return AppContext(user_panel=user_panel, admin_panel=admin_panel)
