"""
scripts/verify_sequences.py
----------------------------
`reset_sequences.sh` sonrası her tablonun auto-increment sayacının o
tablodaki en büyük id'den GERİDE olmadığını doğrular. Salt-okunur bir
kontroldür — hiçbir veriyi değiştirmez.

Kullanım (web container içinde):
    docker compose exec -T web python scripts/verify_sequences.py
"""

from __future__ import annotations

import django
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import User
from django.db import connection

from accounts.models import UserProfile
from audit.models import AuditLog
from billing.models import (
    Apartment,
    ApartmentBillingLine,
    ApartmentComplex,
    ApartmentResident,
    ApprovalRequest,
    BillingRun,
    ComplexAccess,
)

MODELS = [
    User,
    UserProfile,
    ApartmentComplex,
    Apartment,
    ApartmentResident,
    BillingRun,
    ApartmentBillingLine,
    ApprovalRequest,
    ComplexAccess,
    AuditLog,
    LogEntry,
]


def check() -> bool:
    all_ok = True
    with connection.cursor() as cursor:
        for model in MODELS:
            table = model._meta.db_table
            cursor.execute("SELECT pg_get_serial_sequence(%s, 'id')", [table])
            seq_name = cursor.fetchone()[0]
            if seq_name is None:
                continue
            cursor.execute(f'SELECT last_value FROM "{seq_name}"')
            seq_value = cursor.fetchone()[0]
            cursor.execute(f'SELECT COALESCE(MAX(id), 0) FROM "{table}"')
            max_id = cursor.fetchone()[0]
            ok = seq_value >= max_id
            all_ok = all_ok and ok
            status = "OK" if ok else "SORUNLU"
            print(f"{table:32s} sequence={seq_value:<6} max(id)={max_id:<6} -> {status}")
    return all_ok


if __name__ == "__main__":
    if check():
        print("\nTum sequence'ler dogru.")
    else:
        print("\nEN AZ BIR SEQUENCE GERIDE - reset_sequences.sh'i tekrar calistirin.")
        raise SystemExit(1)
