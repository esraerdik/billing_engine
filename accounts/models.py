from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class UserProfile(models.Model):
    """Her Django `User`'a eşlik eden rol bilgisi.

    Kullanıcı adı/şifre bilgisi tamamen `django.contrib.auth.models.User`
    tablosunda tutulur (Django'nun kendi hashleme/doğrulama mekanizmasıyla);
    bu model SADECE "bu kullanıcı admin mi, normal kullanıcı mı" sorusuna
    cevap veren ek bir rol alanı taşır. Böylece giriş ve yetkilendirme
    tamamen veritabanından okunur, kod içinde sabit kullanıcı listesi
    tutulmaz.
    """

    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        USER = "user", "User"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.USER)
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="soft_deleted_users",
    )

    def __str__(self) -> str:
        return f"{self.user.username} ({self.get_role_display()})"

    @property
    def is_admin(self) -> bool:
        return self.role == self.Role.ADMIN

    def mark_deleted(self, *, deleted_by=None) -> None:
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.deleted_by = deleted_by
        self.save(update_fields=["is_deleted", "deleted_at", "deleted_by"])

    def restore(self) -> None:
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by = None
        self.save(update_fields=["is_deleted", "deleted_at", "deleted_by"])
