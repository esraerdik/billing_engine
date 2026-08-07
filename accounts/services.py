"""
services.py (accounts)
-----------------------
Kullanıcı oluşturma/düzenleme/görüntüleme için ince bir servis katmanı.
Şifreler her zaman `User.set_password(...)` / `create_user(...)`
üzerinden Django'nun kendi hash'leme mekanizmasıyla (PBKDF2) saklanır —
hiçbir zaman düz metin olarak veritabanına yazılmaz.
"""

from __future__ import annotations

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Q

from .exceptions import (
    AdminDeactivationForbiddenError,
    LastAdminDeletionError,
    LastActiveAdminError,
    UsernameAlreadyExistsError,
)
from .models import UserProfile


def is_admin_user(user) -> bool:
    """Bir kullanıcının (Django `User` örneğinin) Admin yetkisine sahip
    olup olmadığını belirler. Rol bilgisi `UserProfile.role`'den okunur;
    `is_staff`/`is_superuser`, henüz bir profili olmayan hesaplar
    (örn. `createsuperuser`) için bir güvenlik ağıdır.
    """
    profile = getattr(user, "profile", None)
    if profile is not None and profile.is_deleted:
        return False
    return (
        (profile is not None and profile.role == UserProfile.Role.ADMIN)
        or bool(getattr(user, "is_superuser", False))
        or bool(getattr(user, "is_staff", False))
    )


def is_deleted_user(user) -> bool:
    profile = getattr(user, "profile", None)
    return bool(profile is not None and profile.is_deleted)


def _admin_query() -> Q:
    return Q(profile__is_deleted=False) & (
        Q(profile__role=UserProfile.Role.ADMIN)
        | Q(is_superuser=True)
        | Q(is_staff=True)
    )


def _ensure_other_active_admin_exists(user: User) -> None:
    other_admin_ids = list(
        User.objects.select_for_update()
        .filter(is_active=True)
        .filter(_admin_query())
        .exclude(pk=user.pk)
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    if not other_admin_ids:
        raise LastActiveAdminError(user.username)


def _lock_active_admins() -> list[int]:
    """Eşzamanlı iki pasifleştirmeyi aynı kilit sırasıyla seri hale getirir."""
    return list(
        User.objects.select_for_update()
        .filter(is_active=True)
        .filter(_admin_query())
        .order_by("pk")
        .values_list("pk", flat=True)
    )


@transaction.atomic
def create_user(*, username: str, password: str, role: str = UserProfile.Role.USER) -> User:
    username = username.strip()
    if User.objects.filter(username=username).exists():
        raise UsernameAlreadyExistsError(username)

    is_admin = role == UserProfile.Role.ADMIN
    user = User.objects.create_user(
        username=username,
        password=password,
        is_staff=is_admin,
        is_superuser=is_admin,
    )
    # `accounts.signals.create_user_profile`, kullanıcı kaydedilir
    # kaydedilmez varsayılan (USER) rollü bir profil açar; burada admin
    # panelinde seçilen gerçek role göre güncelliyoruz.
    UserProfile.objects.update_or_create(user=user, defaults={"role": role})
    return user


def list_users(*, include_deleted: bool = False) -> list[User]:
    users = User.objects.select_related("profile")
    if not include_deleted:
        users = users.filter(profile__is_deleted=False)
    return list(users.order_by("username"))


def list_deleted_users() -> list[User]:
    return list(
        User.objects.select_related("profile", "profile__deleted_by")
        .filter(profile__is_deleted=True)
        .order_by("-profile__deleted_at", "username")
    )


def get_user(user_id: int, *, include_deleted: bool = False) -> User:
    users = User.objects.select_related("profile")
    if not include_deleted:
        users = users.filter(profile__is_deleted=False)
    return users.get(pk=user_id)


@transaction.atomic
def update_user(
    *,
    user_id: int,
    username: str,
    role: str,
    is_active: bool,
    new_password: str | None = None,
) -> User:
    _lock_active_admins()
    user = (
        User.objects.select_for_update()
        .select_related("profile")
        .get(pk=user_id, profile__is_deleted=False)
    )

    username = username.strip()
    if username != user.username and User.objects.filter(username=username).exists():
        raise UsernameAlreadyExistsError(username)

    will_remain_admin = role == UserProfile.Role.ADMIN
    if not is_active and (is_admin_user(user) or will_remain_admin):
        raise AdminDeactivationForbiddenError(user.username)
    if (
        user.is_active
        and is_admin_user(user)
        and not will_remain_admin
    ):
        _ensure_other_active_admin_exists(user)

    is_admin = will_remain_admin
    user.username = username
    user.is_active = is_active
    user.is_staff = is_admin
    user.is_superuser = is_admin
    if new_password:
        user.set_password(new_password)
    user.save()

    UserProfile.objects.update_or_create(user=user, defaults={"role": role})
    return user


@transaction.atomic
def set_user_active(user_id: int, is_active: bool) -> User:
    _lock_active_admins()
    user = (
        User.objects.select_for_update()
        .select_related("profile")
        .get(pk=user_id, profile__is_deleted=False)
    )
    if user.is_active and not is_active and is_admin_user(user):
        raise AdminDeactivationForbiddenError(user.username)
    user.is_active = is_active
    user.save(update_fields=["is_active"])
    return user


@transaction.atomic
def delete_user(user_id: int, *, deleted_by: User | None = None) -> User:
    """User satırını koruyarak hesabı erişime kapatır ve silinmiş işaretler."""
    active_admin_ids = _lock_active_admins()
    user = (
        User.objects.select_for_update()
        .select_related("profile")
        .get(pk=user_id, profile__is_deleted=False)
    )
    username = user.username
    if is_admin_user(user):
        if len(active_admin_ids) < 2:
            raise LastAdminDeletionError(username)
    user.is_active = False
    user.save(update_fields=["is_active"])
    user.profile.mark_deleted(deleted_by=deleted_by)
    return user


@transaction.atomic
def restore_user(user_id: int) -> User:
    user = (
        User.objects.select_for_update()
        .select_related("profile")
        .get(pk=user_id, profile__is_deleted=True)
    )
    user.profile.restore()
    user.is_active = True
    user.save(update_fields=["is_active"])
    return user
