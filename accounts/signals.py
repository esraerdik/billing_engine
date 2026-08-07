"""
signals.py
----------
Yeni bir Django `User` oluşturulduğunda, otomatik olarak varsayılan
rollü (`Role.USER`) bir `UserProfile` açar.

Bu sayede Django admin üzerinden "Add user" ile yeni bir kullanıcı
eklendiğinde, rol atamayı unutmak diye bir durum olmaz — varsayılan
rol hemen atanır, admin isterse sonradan kullanıcı düzenleme
ekranından `Admin`'e yükseltebilir (bkz. accounts/admin.py'deki
`UserProfileInline`).
"""

from __future__ import annotations

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import UserProfile


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_profile(sender, instance, created, **kwargs) -> None:
    if created:
        UserProfile.objects.get_or_create(user=instance)
