"""
0002_seed_demo_users
---------------------
Daha önce `accounts/views.py` içinde sabit kodlanmış (hardcoded) demo
hesapları — `admin` / `admin123` ve `user` / `user123` — artık kalıcı
olarak veritabanında tutulur. Bu migration idempotenttir (`get_or_create`
+ `update_or_create` kullanır), tekrar tekrar çalıştırılsa da güvenlidir.
"""

from __future__ import annotations

from django.contrib.auth.hashers import make_password
from django.db import migrations

DEMO_USERS = [
    # (username, password, role, is_staff, is_superuser)
    ("admin", "admin123", "admin", True, True),
    ("user", "user123", "user", False, False),
]


def seed_demo_users(apps, schema_editor):
    User = apps.get_model("auth", "User")
    UserProfile = apps.get_model("accounts", "UserProfile")

    for username, password, role, is_staff, is_superuser in DEMO_USERS:
        user, _created = User.objects.get_or_create(
            username=username,
            defaults={"is_staff": is_staff, "is_superuser": is_superuser},
        )
        user.password = make_password(password)
        user.is_staff = is_staff
        user.is_superuser = is_superuser
        user.save()

        UserProfile.objects.update_or_create(
            user=user, defaults={"role": role}
        )


def noop_reverse(apps, schema_editor):
    """Demo kullanıcılar geri alınmaz — sadece ileri yönde seed edilir."""


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
        ("auth", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_demo_users, noop_reverse),
    ]
