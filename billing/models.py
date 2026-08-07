from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class ApartmentComplex(models.Model):
    name = models.CharField(max_length=200)
    address = models.CharField(max_length=500, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="soft_deleted_complexes",
    )

    class Meta:
        verbose_name = "Apartment complex"
        verbose_name_plural = "Apartment complexes"

    def __str__(self) -> str:
        return self.name

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


class ComplexAccess(models.Model):
    """Bir kullanıcının hangi apartmana (`ApartmentComplex`) erişim
    yetkisi olduğunu tutar.

    Admin rolündeki kullanıcılar (bkz. `accounts.services.is_admin_user`)
    bu tablodan BAĞIMSIZ olarak tüm apartmanlara erişir — bu tabloya
    sadece "User" rolündeki hesapların apartman bazlı yetkilendirmesi
    için satır eklenir. Her apartman, ileride eklenecek Modbus cihazı,
    sayaç/kalorimetre, fatura dönemi ve hesaplama geçmişi kayıtlarının
    doğal olarak izole olduğu merkezi birim olduğundan, yetkilendirme de
    bu birim (`ApartmentComplex`) üzerinden tanımlanır — tekil daire
    bazında değil.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="complex_access",
    )
    complex = models.ForeignKey(
        "ApartmentComplex",
        on_delete=models.CASCADE,
        related_name="user_access",
    )
    granted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "complex"], name="uniq_complexaccess_user_complex"
            )
        ]
        indexes = [
            models.Index(fields=["user"]),
        ]

    def __str__(self) -> str:
        return f"{self.user} → {self.complex.name}"


class Apartment(models.Model):
    complex = models.ForeignKey(
        ApartmentComplex,
        on_delete=models.PROTECT,
        related_name="apartments",
    )
    unit_no = models.CharField(max_length=50)
    block = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text=(
            "Blok/etap adı (opsiyonel) — örn. 'A Blok'. Toplu Excel özetinde "
            "(bkz. invoice_pdf.excel) ayrı bir sütun olarak gösterilir."
        ),
    )
    area_m2 = models.DecimalField(max_digits=10, decimal_places=2)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["complex", "unit_no"],
                name="uniq_apartment_unit_per_complex",
            )
        ]
        indexes = [
            models.Index(fields=["complex", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.complex.name} — {self.unit_no}"


class ApartmentResident(models.Model):
    """Daire sakin geçmişi — taşınma/değişimde eski kayıtlar korunur."""

    apartment = models.ForeignKey(
        Apartment,
        # Sakin geçmişi ikincil (contact) veridir — sayaç okuması/fatura
        # satırı gibi kritik kayıtların aksine (bkz. MeterDevice,
        # ApartmentBillingLine: PROTECT), bir daire silindiğinde sakin
        # geçmişinin de birlikte silinmesi güvenlidir. Bu sayede admin
        # panelinden "silme" işlemi, sakin adı girilmiş bir daire için de
        # çalışabilir.
        on_delete=models.CASCADE,
        related_name="residency_history",
    )
    name = models.CharField(max_length=200)
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["apartment", "-started_at"]),
        ]
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"{self.name} ({self.apartment.unit_no})"

    @property
    def is_current(self) -> bool:
        return self.ended_at is None


class MeterDevice(models.Model):
    class Status(models.TextChoices):
        NORMAL = "normal", "Normal"
        RETRYING = "retrying", "Retry Devam Ediyor"
        FAULTY = "faulty", "Arızalı / Veri Alınamıyor"
        WAITING = "waiting", "Bekleniyor"

    apartment = models.ForeignKey(
        Apartment,
        on_delete=models.PROTECT,
        related_name="meter_devices",
    )
    modbus_address = models.CharField(max_length=100)
    installed_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.WAITING, db_index=True
    )
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_failure_at = models.DateTimeField(null=True, blank=True)
    failure_started_at = models.DateTimeField(null=True, blank=True)
    next_retry_at = models.DateTimeField(null=True, blank=True, db_index=True)
    faulty_since = models.DateTimeField(null=True, blank=True)
    faulty_days = models.PositiveIntegerField(default=0)
    total_retry_count = models.PositiveIntegerField(default=0)
    consecutive_failures = models.PositiveIntegerField(default=0)
    last_error_type = models.CharField(max_length=40, blank=True, default="")
    last_error_message = models.TextField(blank=True, default="")

    class Meta:
        indexes = [
            models.Index(fields=["apartment", "is_active"]),
            models.Index(fields=["is_active", "status", "next_retry_at"]),
        ]

    def __str__(self) -> str:
        return f"Meter {self.modbus_address} ({self.apartment.unit_no})"


class MeterReading(models.Model):
    device = models.ForeignKey(
        MeterDevice,
        on_delete=models.PROTECT,
        related_name="readings",
    )
    raw_value = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        help_text="Kümülatif enerji (Wh)",
    )
    read_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["device", "read_at"]),
        ]
        ordering = ["read_at"]

    def __str__(self) -> str:
        return f"{self.device} @ {self.read_at}: {self.raw_value} Wh"


class ImmutableMeterReadingLogQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise TypeError("Sayaç okuma geçmişi değiştirilemez.")

    def delete(self):
        raise TypeError("Sayaç okuma geçmişi silinemez.")


class MeterReadingLog(models.Model):
    class Status(models.TextChoices):
        SUCCESS = "success", "Başarılı"
        FAILED = "failed", "Başarısız"
        RECOVERED = "recovered", "Sorun Çözüldü"

    class ErrorType(models.TextChoices):
        TIMEOUT = "timeout", "Timeout"
        CONNECTION = "connection_error", "Connection Error"
        MODBUS = "modbus_exception", "Modbus Exception"
        INVALID_DATA = "invalid_data", "Geçersiz Veri"
        UNEXPECTED_RESPONSE = "unexpected_response", "Beklenmeyen Cevap"
        UNEXPECTED = "unexpected_error", "Beklenmeyen Hata"

    device = models.ForeignKey(
        MeterDevice,
        on_delete=models.PROTECT,
        related_name="reading_history",
    )
    complex = models.ForeignKey(
        ApartmentComplex,
        on_delete=models.PROTECT,
        related_name="meter_reading_history",
    )
    apartment = models.ForeignKey(
        Apartment,
        on_delete=models.PROTECT,
        related_name="meter_reading_history",
    )
    read_at = models.DateTimeField(db_index=True)
    energy_value = models.DecimalField(
        max_digits=18, decimal_places=4, null=True, blank=True
    )
    status = models.CharField(max_length=20, choices=Status.choices, db_index=True)
    retry_number = models.PositiveIntegerField(default=0)
    error_type = models.CharField(
        max_length=40, choices=ErrorType.choices, blank=True, default=""
    )
    error_description = models.TextField(blank=True, default="")
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    device_identifier = models.CharField(max_length=100, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = ImmutableMeterReadingLogQuerySet.as_manager()

    class Meta:
        ordering = ["-read_at", "-id"]
        indexes = [
            models.Index(fields=["complex", "-read_at"]),
            models.Index(fields=["status", "-read_at"]),
            models.Index(fields=["device", "-read_at"]),
        ]
        verbose_name = "Sayaç okuma geçmişi"
        verbose_name_plural = "Sayaç okuma geçmişi"

    def save(self, *args, **kwargs):
        if self.pk:
            raise TypeError("Sayaç okuma geçmişi değiştirilemez.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Sayaç okuma geçmişi silinemez.")

    def __str__(self) -> str:
        return f"{self.device} - {self.get_status_display()} - {self.read_at}"


class MeterAlert(models.Model):
    class Severity(models.TextChoices):
        WARNING = "warning", "Uyarı"
        CRITICAL = "critical", "Kritik"

    device = models.ForeignKey(
        MeterDevice,
        on_delete=models.PROTECT,
        related_name="alerts",
    )
    severity = models.CharField(max_length=20, choices=Severity.choices)
    message = models.TextField()
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["device"],
                condition=models.Q(is_active=True),
                name="uniq_active_meter_alert_per_device",
            )
        ]
        indexes = [
            models.Index(fields=["is_active", "severity", "-updated_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.device}: {self.get_severity_display()}"


class BillingRun(models.Model):
    complex = models.ForeignKey(
        ApartmentComplex,
        on_delete=models.PROTECT,
        related_name="billing_runs",
    )
    period_year = models.PositiveSmallIntegerField()
    period_month = models.PositiveSmallIntegerField()
    window_start_date = models.DateField()
    window_end_date = models.DateField()
    total_bill = models.DecimalField(max_digits=14, decimal_places=2)
    total_fixed_amount = models.DecimalField(max_digits=14, decimal_places=2)
    total_consumption_amount = models.DecimalField(max_digits=14, decimal_places=2)
    total_area = models.DecimalField(max_digits=14, decimal_places=2)
    total_energy = models.DecimalField(max_digits=18, decimal_places=4)
    run_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="billing_runs",
    )
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["complex", "period_year", "period_month"]),
            # Tarih aralığı çakışma kontrolü (bkz. billing/services.py
            # `_validate_billing_window`) bu alanlar üzerinden sorgu atar;
            # 20 yıllık veri birikiminde bu sorgunun indekssiz kalması
            # tablo taramasına yol açar.
            models.Index(fields=["complex", "window_start_date", "window_end_date"]),
        ]
        ordering = ["-recorded_at"]

    def __str__(self) -> str:
        return (
            f"{self.complex.name} {self.period_year}-{self.period_month:02d} "
            f"({self.window_start_date} → {self.window_end_date})"
        )


class ApartmentBillingLine(models.Model):
    class Status(models.TextChoices):
        NORMAL = "normal", "Normal"
        ANOMALY = "anomaly", "Anomaly"

    billing_run = models.ForeignKey(
        BillingRun,
        on_delete=models.PROTECT,
        related_name="lines",
    )
    apartment = models.ForeignKey(
        Apartment,
        on_delete=models.PROTECT,
        related_name="billing_lines",
    )
    start_reading = models.ForeignKey(
        MeterReading,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="billing_lines_as_start",
    )
    end_reading = models.ForeignKey(
        MeterReading,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="billing_lines_as_end",
    )
    energy_consumed = models.DecimalField(max_digits=18, decimal_places=4)
    start_energy_value = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        null=True,
        blank=True,
        help_text=(
            "Bu satırın tüketiminin hesaplandığı başlangıç (ilk) kümülatif "
            "enerji endeksi. Modbus okuması varsa `start_reading.raw_value` "
            "ile aynıdır; manuel girişte kullanıcının panelden girdiği "
            "'İlk Enerji' değeridir. Hiçbiri yoksa `null`."
        ),
    )
    end_energy_value = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        null=True,
        blank=True,
        help_text=(
            "Bu satırın tüketiminin hesaplandığı bitiş (son) kümülatif "
            "enerji endeksi. Modbus okuması varsa `end_reading.raw_value` "
            "ile aynıdır; manuel girişte kullanıcının panelden girdiği "
            "'Son Enerji' değeridir. Hiçbiri yoksa `null`."
        ),
    )
    area_ratio = models.DecimalField(max_digits=12, decimal_places=6)
    energy_ratio = models.DecimalField(max_digits=12, decimal_places=6)
    fixed_share = models.DecimalField(max_digits=14, decimal_places=2)
    consumption_share = models.DecimalField(max_digits=14, decimal_places=2)
    total_payable = models.DecimalField(max_digits=14, decimal_places=2)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.NORMAL,
    )

    class Meta:
        indexes = [
            models.Index(fields=["apartment", "billing_run"]),
        ]

    def __str__(self) -> str:
        return f"{self.apartment.unit_no} — {self.billing_run}"


class ApprovalRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        DENIED = "denied", "Denied"

    period_year = models.PositiveSmallIntegerField()
    period_month = models.PositiveSmallIntegerField()
    window_start_date = models.DateField(
        null=True,
        blank=True,
        help_text=(
            "Yeniden hesaplama talebinin başlangıç tarihi. Özellik eklenmeden "
            "önceki eski taleplerde boş olabilir."
        ),
    )
    window_end_date = models.DateField(
        null=True,
        blank=True,
        help_text=(
            "Yeniden hesaplama talebinin bitiş tarihi. Özellik eklenmeden "
            "önceki eski taleplerde boş olabilir."
        ),
    )
    complex = models.ForeignKey(
        ApartmentComplex,
        on_delete=models.PROTECT,
        related_name="approval_requests",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="billing_approval_requests",
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="billing_approval_decisions",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    billing_run = models.OneToOneField(
        BillingRun,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="approval_request",
        help_text=(
            "Bu onay kullanılarak başarıyla oluşturulan yeniden hesaplama. "
            "Boşsa onay henüz tüketilmemiştir."
        ),
    )

    class Meta:
        indexes = [
            models.Index(
                fields=["complex", "period_year", "period_month", "status"]
            ),
            models.Index(
                fields=[
                    "complex",
                    "window_start_date",
                    "window_end_date",
                    "status",
                ]
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.complex.name} "
            f"{self.window_start_date or self.period_year}–"
            f"{self.window_end_date or self.period_month} "
            f"({self.status})"
        )
