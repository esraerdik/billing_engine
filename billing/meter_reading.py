from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from time import perf_counter
from typing import Protocol

from django.db import transaction
from django.utils import timezone

from audit.models import AuditLog
from audit.services import record_audit

from .models import MeterAlert, MeterDevice, MeterReading, MeterReadingLog


class MeterReader(Protocol):
    """Gerçek Modbus TCP adaptörünün ileride uygulayacağı küçük arayüz."""

    def read_energy(self, device: MeterDevice) -> Decimal | float | int:
        ...


class MeterReadError(Exception):
    error_type = MeterReadingLog.ErrorType.UNEXPECTED


class ModbusExceptionError(MeterReadError):
    error_type = MeterReadingLog.ErrorType.MODBUS


class UnexpectedResponseError(MeterReadError):
    error_type = MeterReadingLog.ErrorType.UNEXPECTED_RESPONSE


class InvalidMeterDataError(MeterReadError):
    error_type = MeterReadingLog.ErrorType.INVALID_DATA


@dataclass(frozen=True)
class RetryPolicy:
    """Kısa aralıklardan başlayıp 24 saat sonrasında günlük denemeye geçen politika."""

    intervals: tuple[timedelta, ...] = (
        timedelta(minutes=1),
        timedelta(minutes=5),
        timedelta(minutes=15),
        timedelta(minutes=30),
        timedelta(hours=1),
        timedelta(hours=2),
        timedelta(hours=4),
        timedelta(hours=6),
    )
    failure_window: timedelta = timedelta(hours=24)
    faulty_retry_interval: timedelta = timedelta(days=1)

    def next_delay(self, retry_number: int, *, faulty: bool) -> timedelta:
        if faulty:
            return self.faulty_retry_interval
        index = max(0, min(retry_number - 1, len(self.intervals) - 1))
        return self.intervals[index]


DEFAULT_RETRY_POLICY = RetryPolicy()


def _coerce_energy(value) -> Decimal:
    try:
        energy = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise InvalidMeterDataError("Sayaç sayısal bir enerji değeri döndürmedi.") from exc
    if not energy.is_finite() or energy < 0:
        raise InvalidMeterDataError("Sayaç geçersiz bir enerji değeri döndürdü.")
    return energy


def _error_details(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, TimeoutError):
        error_type = MeterReadingLog.ErrorType.TIMEOUT
    elif isinstance(exc, ConnectionError):
        error_type = MeterReadingLog.ErrorType.CONNECTION
    elif isinstance(exc, MeterReadError):
        error_type = exc.error_type
    else:
        error_type = MeterReadingLog.ErrorType.UNEXPECTED
    return error_type, (str(exc).strip() or exc.__class__.__name__)[:2000]


def _audit_meter(device: MeterDevice, *, action: str, success: bool, description: str):
    return record_audit(
        action=action,
        category=AuditLog.Category.SYSTEM,
        success=success,
        object_type="MeterDevice",
        object_id=device.id,
        object_repr=str(device),
        description=description,
        metadata={
            "complex_id": device.apartment.complex_id,
            "apartment_id": device.apartment_id,
            "modbus_address": device.modbus_address,
        },
    )


def _upsert_alert(device: MeterDevice, *, faulty: bool) -> MeterAlert:
    if faulty:
        severity = MeterAlert.Severity.CRITICAL
        message = (
            f"Daire {device.apartment.unit_no} için enerji verisi alınamadı. "
            "Sayaç arızalı olarak işaretlendi."
        )
    else:
        severity = MeterAlert.Severity.WARNING
        message = (
            f"Daire {device.apartment.unit_no} sayaç verisi alınamadı. "
            "Sistem otomatik olarak yeniden okumaya devam ediyor."
        )
    alert = MeterAlert.objects.filter(device=device, is_active=True).first()
    if alert is None:
        return MeterAlert.objects.create(
            device=device, severity=severity, message=message
        )
    alert.severity = severity
    alert.message = message
    alert.save(update_fields=["severity", "message", "updated_at"])
    return alert


def _resolve_alerts(device: MeterDevice, resolved_at) -> None:
    MeterAlert.objects.filter(device=device, is_active=True).update(
        is_active=False, resolved_at=resolved_at, updated_at=resolved_at
    )


@transaction.atomic
def _record_success(
    device: MeterDevice,
    *,
    energy: Decimal,
    read_at,
    duration_ms: int,
) -> MeterReadingLog:
    device = MeterDevice.objects.select_for_update().select_related(
        "apartment", "apartment__complex"
    ).get(pk=device.pk)
    was_retrying = device.consecutive_failures > 0
    was_faulty = device.status == MeterDevice.Status.FAULTY

    MeterReading.objects.create(device=device, raw_value=energy, read_at=read_at)
    history_status = (
        MeterReadingLog.Status.RECOVERED
        if was_retrying
        else MeterReadingLog.Status.SUCCESS
    )
    log = MeterReadingLog.objects.create(
        device=device,
        complex=device.apartment.complex,
        apartment=device.apartment,
        read_at=read_at,
        energy_value=energy,
        status=history_status,
        retry_number=device.consecutive_failures,
        duration_ms=duration_ms,
        device_identifier=device.modbus_address,
        error_description="Sorun çözüldü." if was_retrying else "",
    )

    device.status = MeterDevice.Status.NORMAL
    device.last_success_at = read_at
    device.failure_started_at = None
    device.next_retry_at = None
    device.faulty_since = None
    device.faulty_days = 0
    device.consecutive_failures = 0
    device.last_error_type = ""
    device.last_error_message = ""
    device.save(
        update_fields=[
            "status", "last_success_at", "failure_started_at", "next_retry_at",
            "faulty_since", "faulty_days", "consecutive_failures",
            "last_error_type", "last_error_message",
        ]
    )
    _resolve_alerts(device, read_at)

    if was_retrying:
        _audit_meter(
            device,
            action="meter_retry_success",
            success=True,
            description="Sayaç retry sonrasında başarıyla okundu.",
        )
    if was_faulty:
        _audit_meter(
            device,
            action="meter_recovered",
            success=True,
            description="Arızalı sayaç tekrar çalıştı.",
        )
    return log


@transaction.atomic
def _record_failure(
    device: MeterDevice,
    *,
    read_at,
    duration_ms: int,
    error_type: str,
    error_description: str,
    retry_policy: RetryPolicy,
) -> MeterReadingLog:
    device = MeterDevice.objects.select_for_update().select_related(
        "apartment", "apartment__complex"
    ).get(pk=device.pk)
    first_failure = device.failure_started_at is None
    if first_failure:
        device.failure_started_at = read_at

    device.consecutive_failures += 1
    device.total_retry_count += 1
    elapsed = read_at - device.failure_started_at
    became_faulty = (
        device.status != MeterDevice.Status.FAULTY
        and elapsed >= retry_policy.failure_window
    )
    if elapsed >= retry_policy.failure_window:
        device.status = MeterDevice.Status.FAULTY
        if device.faulty_since is None:
            device.faulty_since = read_at
        device.faulty_days = max(1, (read_at.date() - device.faulty_since.date()).days + 1)
    else:
        device.status = MeterDevice.Status.RETRYING

    is_faulty = device.status == MeterDevice.Status.FAULTY
    device.last_failure_at = read_at
    next_retry_at = read_at + retry_policy.next_delay(
        device.consecutive_failures, faulty=is_faulty
    )
    if not is_faulty:
        failure_deadline = device.failure_started_at + retry_policy.failure_window
        next_retry_at = min(next_retry_at, failure_deadline)
    device.next_retry_at = next_retry_at
    device.last_error_type = error_type
    device.last_error_message = error_description
    device.save(
        update_fields=[
            "status", "last_failure_at", "failure_started_at", "next_retry_at",
            "faulty_since", "faulty_days", "total_retry_count",
            "consecutive_failures", "last_error_type", "last_error_message",
        ]
    )

    log = MeterReadingLog.objects.create(
        device=device,
        complex=device.apartment.complex,
        apartment=device.apartment,
        read_at=read_at,
        status=MeterReadingLog.Status.FAILED,
        retry_number=device.consecutive_failures,
        error_type=error_type,
        error_description=error_description,
        duration_ms=duration_ms,
        device_identifier=device.modbus_address,
    )
    _upsert_alert(device, faulty=is_faulty)

    if first_failure:
        action = "meter_retry_started"
        description = "Sayaç okuması başarısız oldu; otomatik retry başladı."
    else:
        action = "meter_retry_failed"
        description = "Sayaç retry okuması başarısız oldu."
    _audit_meter(device, action=action, success=False, description=description)
    if became_faulty:
        _audit_meter(
            device,
            action="meter_became_faulty",
            success=False,
            description="24 saat boyunca veri alınamayan sayaç arızalı işaretlendi.",
        )
    return log


def read_meter(
    device: MeterDevice,
    reader: MeterReader,
    *,
    now=None,
    retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
) -> MeterReadingLog:
    """Bir denemeyi çalıştırır; başarılı ve başarısız sonucu mutlaka geçmişe yazar."""
    read_at = now or timezone.now()
    started = perf_counter()
    try:
        energy = _coerce_energy(reader.read_energy(device))
    except Exception as exc:
        duration_ms = max(0, round((perf_counter() - started) * 1000))
        error_type, description = _error_details(exc)
        return _record_failure(
            device,
            read_at=read_at,
            duration_ms=duration_ms,
            error_type=error_type,
            error_description=description,
            retry_policy=retry_policy,
        )
    duration_ms = max(0, round((perf_counter() - started) * 1000))
    return _record_success(
        device, energy=energy, read_at=read_at, duration_ms=duration_ms
    )


def run_due_retries(
    reader: MeterReader,
    *,
    now=None,
    retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
) -> list[MeterReadingLog]:
    """Harici scheduler tarafından çağrılacak, zamanı gelen retry giriş noktası."""
    current_time = now or timezone.now()
    devices = (
        MeterDevice.objects.filter(
            is_active=True,
            next_retry_at__isnull=False,
            next_retry_at__lte=current_time,
        )
        .select_related("apartment", "apartment__complex")
        .order_by("next_retry_at", "id")
    )
    return [
        read_meter(device, reader, now=current_time, retry_policy=retry_policy)
        for device in devices
    ]


def run_daily_readings(
    reader: MeterReader,
    *,
    now=None,
    retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
) -> list[MeterReadingLog]:
    """Günlük scheduler giriş noktası; arızalı sayaçlar dahil tüm aktif sayaçları dener."""
    current_time = now or timezone.now()
    devices = MeterDevice.objects.filter(is_active=True).select_related(
        "apartment", "apartment__complex"
    ).order_by("id")
    return [
        read_meter(device, reader, now=current_time, retry_policy=retry_policy)
        for device in devices
    ]


def list_active_meter_alerts(*, complex_ids=None):
    alerts = MeterAlert.objects.filter(is_active=True).select_related(
        "device", "device__apartment", "device__apartment__complex"
    )
    if complex_ids is not None:
        alerts = alerts.filter(device__apartment__complex_id__in=complex_ids)
    return list(alerts.order_by("-severity", "-updated_at"))
