"""
auth.py
-------
GEÇİCİ, sabit kodlu kullanıcı doğrulama.

Bu dosya `calculator.py` / `authorization.py` / `history.py` ile AYNI
KATEGORİDE DEĞİLDİR — onlar kalıcı iş mantığı; bu ise "şimdilik iki
kullanıcı olsun" isteği gereği yalnızca UI aşamasını başlatabilmek
için geçici, yerleşik bir kullanıcı listesidir.

İleride gerçek bir kimlik doğrulama sistemi (veritabanı + hash'lenmiş
şifreler) eklenince yalnızca bu dosya değişir; `login_window.py`
sadece `authenticate()` fonksiyonunu çağırır, iç detaylarla hiç
ilgilenmez — aynı `RunPolicyProvider` deseninde olduğu gibi, dışa
açık imza sabit kalırken iç gerçekleştirim değişebilir.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class UserRole(Enum):
    """Giriş yapan kullanıcının yönlendirileceği paneli belirler."""

    USER = "user"
    ADMIN = "admin"


@dataclass(frozen=True)
class _Credential:
    """Tek bir sabit kodlu kullanıcı kaydı (kullanıcı adı, şifre, rol)."""

    username: str
    password: str
    role: UserRole


# Şimdilik yalnızca iki kullanıcı. Gerçek bir kimlik doğrulama sistemi
# eklendiğinde bu liste tamamen kaldırılıp `authenticate()`'in içi
# değiştirilecek; dışarıdan çağıran kod (login_window.py) hiç etkilenmez.
_AUTHORIZED_USERS: tuple[_Credential, ...] = (
    _Credential(username="admin", password="admin123", role=UserRole.ADMIN),
    _Credential(username="user", password="user123", role=UserRole.USER),
)


def authenticate(username: str, password: str) -> UserRole | None:
    """Kullanıcı adı/şifre eşleşirse ilgili rolü döndürür.

    Eşleşme yoksa `None` döner — bu bir hata değil, "giriş başarısız"
    anlamına gelen geçerli bir sonuçtur; çağıran kod (login_window.py)
    bunu kontrol edip uygun mesajı göstermekle sorumludur.
    """
    for credential in _AUTHORIZED_USERS:
        if credential.username == username and credential.password == password:
            return credential.role
    return None
