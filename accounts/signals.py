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
def create_user_profile(sender, instance, created, raw=False, **kwargs) -> None:
    # `raw=True`: `loaddata` bir fixture yüklerken bu sinyali de tetikler
    # ama o an referans bütünlüğü henüz garanti değildir (bkz. Django
    # dokümantasyonu). Bu kontrol olmadan, fixture'daki her yeni User
    # için burada bir UserProfile otomatik açılır ve fixture'ın KENDİ
    # UserProfile kaydıyla `user_id` üzerinde UniqueViolation çakışması
    # yaşanır — normal (raw olmayan) kullanıcı oluşturmada davranış
    # değişmez.
    if created and not raw:
        UserProfile.objects.get_or_create(user=instance)
