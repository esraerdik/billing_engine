"""Kullanıcı yönetimine özgü uygulama seviyesi hatalar."""

from __future__ import annotations


class UsernameAlreadyExistsError(Exception):
    def __init__(self, username: str) -> None:
        self.username = username
        super().__init__(f"“{username}” kullanıcı adı zaten kullanılıyor.")


class LastActiveAdminError(Exception):
    """Sistemin yönetici erişimini kaybetmesine yol açacak işlemi engeller."""

    def __init__(self, username: str) -> None:
        self.username = username
        super().__init__(
            "Son aktif yönetici pasifleştirilemez. "
            "Sistemde en az bir aktif yönetici bulunmalıdır."
        )


class AdminDeactivationForbiddenError(Exception):
    def __init__(self, username: str) -> None:
        self.username = username
        super().__init__("Admin kullanıcıları pasifleştirilemez.")


class LastAdminDeletionError(Exception):
    def __init__(self, username: str) -> None:
        self.username = username
        super().__init__(
            "Son yönetici silinemez. Bir yöneticiyi silebilmek için "
            "sistemde en az iki yönetici bulunmalıdır."
        )


class AdminUserProtectedError(Exception):
    """Eski entegrasyonlarla geriye dönük uyumluluk için korunan hata türü."""

    def __init__(self, username: str) -> None:
        self.username = username
        super().__init__(
            f"“{username}” bir sistem yöneticisi (Admin) hesabıdır ve "
            "silinemez. Gerekirse önce rolünü değiştirin veya hesabı "
            "pasif hale getirin."
        )


class UserInUseError(Exception):
    """Kullanıcı silinmek istendiğinde, kendisine bağlı (fatura çalıştırma,
    onay kaydı vb. `PROTECT` ilişkili) kayıtlar bulunduğu için silme
    işlemi reddedildiğinde fırlatılır. Bu durumda kullanıcı tamamen
    silinmek yerine pasif hale getirilmelidir.
    """

    def __init__(self, username: str) -> None:
        self.username = username
        super().__init__(
            f"“{username}” kullanıcısı silinemedi: bu kullanıcıya ait "
            "fatura/onay kayıtları bulunduğu için silme işlemi "
            "yapılamıyor. Bunun yerine kullanıcıyı pasif hale "
            "getirebilirsiniz."
        )
