from django.conf import settings
from django.db import models


class ImmutableAuditLogQuerySet(models.QuerySet):
    def update(self, **kwargs):
        # Kullanıcı silindiğinde Django'nun SET_NULL collector'ı yalnızca
        # ilişkisel alanı boşaltır; username/rol snapshot'ı logda kalır.
        if kwargs in ({"user": None}, {"user_id": None}):
            return super().update(**kwargs)
        raise TypeError("Denetim kayıtları değiştirilemez.")

    def delete(self):
        raise TypeError("Denetim kayıtları silinemez.")


class AuditLog(models.Model):
    class Category(models.TextChoices):
        AUTHENTICATION = "authentication", "Kimlik Doğrulama"
        USER = "user", "Kullanıcı"
        COMPLEX = "complex", "Bina"
        APARTMENT = "apartment", "Daire"
        BILLING = "billing", "Faturalandırma"
        SYSTEM = "system", "Sistem"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_logs",
    )
    username = models.CharField(max_length=150, blank=True)
    user_role = models.CharField(max_length=30, blank=True)
    action = models.CharField(max_length=80, db_index=True)
    category = models.CharField(max_length=30, choices=Category.choices, db_index=True)
    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    success = models.BooleanField(default=True, db_index=True)
    object_type = models.CharField(max_length=80, blank=True)
    object_id = models.CharField(max_length=100, blank=True, db_index=True)
    object_repr = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True, db_index=True)

    objects = ImmutableAuditLogQuerySet.as_manager()

    class Meta:
        ordering = ["-occurred_at", "-id"]
        indexes = [
            models.Index(fields=["category", "-occurred_at"]),
            models.Index(fields=["user", "-occurred_at"]),
            models.Index(fields=["success", "-occurred_at"]),
            models.Index(fields=["archived_at", "-occurred_at"]),
        ]
        verbose_name = "Sistem logu"
        verbose_name_plural = "Sistem logları"

    def save(self, *args, **kwargs):
        if self.pk:
            raise TypeError("Denetim kayıtları değiştirilemez.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Denetim kayıtları silinemez.")

    def __str__(self) -> str:
        return f"{self.occurred_at:%Y-%m-%d %H:%M:%S} {self.action}"
