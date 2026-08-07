"""Audit Log işlem kodlarının yalnızca arayüzde kullanılan Türkçe adları."""

# Her işlem ailesinin ilk elemanı arayüzde ve filtre URL'sinde kullanılan
# kanonik koddur. Diğer kodlar geçmiş kayıtlarla uyumluluk için aynı aileye
# bağlanan eski/alternatif kodlardır.
ACTION_GROUPS = {
    "login_success": ("Başarılı Giriş", ()),
    "login_failed": ("Başarısız Giriş", ()),
    "logout": ("Çıkış Yapıldı", ()),
    "user_create": ("Kullanıcı Oluşturuldu", ("user_created",)),
    "user_update": ("Kullanıcı Güncellendi", ("user_updated",)),
    "password_change": ("Şifre Değiştirildi", ()),
    "user_activated": ("Kullanıcı Aktif Edildi", ()),
    "user_deactivated": ("Kullanıcı Pasifleştirildi", ()),
    "user_soft_deleted": (
        "Kullanıcı Silindi",
        ("user_delete", "user_deleted"),
    ),
    "user_restored": ("Kullanıcı Geri Yüklendi", ()),
    "admin_deleted": ("Yönetici Silindi", ()),
    "admin_deletion_blocked": ("Yönetici Silme İşlemi Engellendi", ()),
    "admin_deactivation_blocked": (
        "Yönetici Pasifleştirme İşlemi Engellendi",
        (),
    ),
    "admin_reactivated": ("Yönetici Yeniden Aktif Edildi", ()),
    "complex_create": ("Apartman Oluşturuldu", ("building_created",)),
    "complex_update": ("Apartman Güncellendi", ("building_updated",)),
    "complex_soft_deleted": (
        "Apartman Silindi",
        ("complex_delete", "complex_deleted", "building_deleted"),
    ),
    "complex_restored": ("Apartman Geri Yüklendi", ("building_restored",)),
    "apartment_create": ("Daire Oluşturuldu", ("apartment_created",)),
    "apartment_update": ("Daire Güncellendi", ("apartment_updated",)),
    "apartment_delete": ("Daire Silindi", ("apartment_deleted",)),
    "billing_create": ("Faturalandırma Yapıldı", ("billing_created",)),
    "rebilling": ("Yeniden Faturalandırma Yapıldı", ()),
    "rebilling_request_create": (
        "Yeniden Faturalandırma Talebi Oluşturuldu",
        (),
    ),
    "billing_approval": ("Onay Verildi", ("approval_granted",)),
    "billing_rejection": ("Talep Reddedildi", ("approval_rejected",)),
    "pdf_create": ("PDF Oluşturuldu", ("pdf_created",)),
    "bulk_pdf_excel_create": ("Toplu PDF/Excel Paketi Oluşturuldu", ()),
    "zip_created": ("ZIP Oluşturuldu", ()),
    "excel_created": ("Excel Oluşturuldu", ()),
    "meter_retry_started": ("Sayaç Yeniden Okuma Süreci Başladı", ()),
    "meter_retry_failed": ("Sayaç Yeniden Okuma Denemesi Başarısız", ()),
    "meter_retry_success": ("Sayaç Yeniden Okuma Denemesi Başarılı", ()),
    "meter_became_faulty": ("Sayaç Arızalı Olarak İşaretlendi", ()),
    "meter_recovered": ("Sayaç Tekrar Çalıştı", ()),
    "unexpected_error": ("Beklenmeyen Sistem Hatası", ()),
}

ACTION_ALIASES = {
    alias: canonical
    for canonical, (_, aliases) in ACTION_GROUPS.items()
    for alias in aliases
}

# Dışarıdan bu sözlüğü kullanan kodlarla geriye dönük uyumluluk korunur.
ACTION_LABELS = {
    code: label
    for canonical, (label, aliases) in ACTION_GROUPS.items()
    for code in (canonical, *aliases)
}

UNKNOWN_ACTION_LABEL = "Diğer Sistem İşlemi"


def get_action_key(action: str) -> str:
    """Teknik işlem kodunun ait olduğu kanonik arayüz anahtarını döndürür."""
    normalized_action = (action or "").strip().lower()
    return ACTION_ALIASES.get(normalized_action, normalized_action)


def get_action_label(action: str) -> str:
    """Teknik kodu değiştirmeden kullanıcı dostu adını döndürür."""
    canonical_action = get_action_key(action)
    group = ACTION_GROUPS.get(canonical_action)
    return group[0] if group else UNKNOWN_ACTION_LABEL


def get_action_codes(action: str) -> tuple[str, ...]:
    """Bir filtre seçiminin kapsadığı güncel ve geçmiş teknik kodları döndürür."""
    canonical_action = get_action_key(action)
    group = ACTION_GROUPS.get(canonical_action)
    codes = (canonical_action, *(group[1] if group else ()))

    # Eski kurulumlarda büyük harfle tutulmuş event kodları da aynı filtreye girer.
    return tuple(dict.fromkeys((*codes, *(code.upper() for code in codes))))


def build_action_choices(actions) -> list[tuple[str, str]]:
    """Veritabanındaki kodlardan tekrarsız ve Türkçe filtre seçenekleri üretir."""
    choices = {}
    for action in actions:
        canonical_action = get_action_key(action)
        choices.setdefault(canonical_action, get_action_label(canonical_action))
    return sorted(choices.items(), key=lambda item: (item[1], item[0]))
