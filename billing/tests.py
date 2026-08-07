"""
tests.py (billing)
--------------------
`billing` app için testler.

    - `RecalculationApprovalRequestTests` (Django `TestCase`): daha önce
      faturalandırılmış bir tarih aralığıyla çakışan yeni bir hesaplama
      talebinin (kısmi çakışma dâhil) doğrudan çalışmayıp admin onay
      akışına (`ApprovalRequest`) düştüğünü uçtan uca doğrular.

Çalıştırmak için:
    python manage.py test billing -v 2
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from audit.models import AuditLog

from .models import (
    Apartment,
    ApartmentComplex,
    ApprovalRequest,
    BillingRun,
    ComplexAccess,
    MeterAlert,
    MeterDevice,
    MeterReading,
    MeterReadingLog,
)
from domain.exceptions import AdminApprovalRequiredError

from .services import (
    approve_request,
    deny_request,
    list_pending_approval_requests,
    run_billing_or_request_approval,
)
from .meter_reading import (
    RetryPolicy,
    read_meter,
    run_daily_readings,
    run_due_retries,
)


class _SuccessfulReader:
    def __init__(self, value=Decimal("123.4567")):
        self.value = value

    def read_energy(self, device):
        return self.value


class _TimeoutReader:
    def read_energy(self, device):
        raise TimeoutError("Cihaz zaman aşımına uğradı.")


class MeterReadingTrackingTests(TestCase):
    def setUp(self) -> None:
        self.complex = ApartmentComplex.objects.create(name="Modbus Binası")
        self.apartment = Apartment.objects.create(
            complex=self.complex, unit_no="203", area_m2=Decimal("80.00")
        )
        self.device = MeterDevice.objects.create(
            apartment=self.apartment,
            modbus_address="10.0.0.10:502/1",
            installed_at=timezone.now(),
        )
        self.policy = RetryPolicy(
            intervals=(timedelta(minutes=1), timedelta(minutes=5)),
            failure_window=timedelta(hours=24),
            faulty_retry_interval=timedelta(days=1),
        )
        self.t0 = timezone.make_aware(datetime(2026, 8, 1, 9, 0))

    def test_success_saves_energy_history_and_normal_status(self) -> None:
        log = read_meter(
            self.device, _SuccessfulReader(), now=self.t0, retry_policy=self.policy
        )
        self.device.refresh_from_db()
        self.assertEqual(log.status, MeterReadingLog.Status.SUCCESS)
        self.assertEqual(log.energy_value, Decimal("123.4567"))
        self.assertEqual(self.device.status, MeterDevice.Status.NORMAL)
        self.assertEqual(self.device.last_success_at, self.t0)
        self.assertTrue(
            MeterReading.objects.filter(
                device=self.device, raw_value=Decimal("123.4567"), read_at=self.t0
            ).exists()
        )

    def test_failure_starts_retry_creates_warning_and_audit(self) -> None:
        log = read_meter(
            self.device, _TimeoutReader(), now=self.t0, retry_policy=self.policy
        )
        self.device.refresh_from_db()
        self.assertEqual(log.status, MeterReadingLog.Status.FAILED)
        self.assertEqual(log.error_type, MeterReadingLog.ErrorType.TIMEOUT)
        self.assertEqual(log.retry_number, 1)
        self.assertEqual(self.device.status, MeterDevice.Status.RETRYING)
        self.assertEqual(self.device.next_retry_at, self.t0 + timedelta(minutes=1))
        self.assertTrue(
            MeterAlert.objects.filter(
                device=self.device,
                severity=MeterAlert.Severity.WARNING,
                is_active=True,
            ).exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(
                action="meter_retry_started",
                object_id=str(self.device.id),
                success=False,
            ).exists()
        )

    def test_24_hour_failure_marks_faulty_but_daily_retry_continues(self) -> None:
        read_meter(
            self.device, _TimeoutReader(), now=self.t0, retry_policy=self.policy
        )
        after_24_hours = self.t0 + timedelta(hours=24)
        read_meter(
            self.device,
            _TimeoutReader(),
            now=after_24_hours,
            retry_policy=self.policy,
        )
        self.device.refresh_from_db()
        self.assertEqual(self.device.status, MeterDevice.Status.FAULTY)
        self.assertEqual(self.device.faulty_days, 1)
        self.assertEqual(
            self.device.next_retry_at, after_24_hours + timedelta(days=1)
        )
        self.assertTrue(
            MeterAlert.objects.filter(
                device=self.device,
                severity=MeterAlert.Severity.CRITICAL,
                is_active=True,
            ).exists()
        )
        daily_logs = run_daily_readings(
            _TimeoutReader(),
            now=after_24_hours + timedelta(days=1),
            retry_policy=self.policy,
        )
        self.assertEqual(len(daily_logs), 1)
        self.device.refresh_from_db()
        self.assertEqual(self.device.status, MeterDevice.Status.FAULTY)
        self.assertTrue(
            AuditLog.objects.filter(action="meter_became_faulty").exists()
        )

    def test_recovery_closes_alert_and_records_resolution(self) -> None:
        read_meter(
            self.device, _TimeoutReader(), now=self.t0, retry_policy=self.policy
        )
        faulty_at = self.t0 + timedelta(hours=24)
        read_meter(
            self.device, _TimeoutReader(), now=faulty_at, retry_policy=self.policy
        )
        recovery_log = read_meter(
            self.device,
            _SuccessfulReader(Decimal("200.0000")),
            now=faulty_at + timedelta(days=1),
            retry_policy=self.policy,
        )
        self.device.refresh_from_db()
        self.assertEqual(recovery_log.status, MeterReadingLog.Status.RECOVERED)
        self.assertEqual(self.device.status, MeterDevice.Status.NORMAL)
        self.assertEqual(self.device.consecutive_failures, 0)
        self.assertFalse(
            MeterAlert.objects.filter(device=self.device, is_active=True).exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(action="meter_retry_success").exists()
        )
        self.assertTrue(AuditLog.objects.filter(action="meter_recovered").exists())

    def test_due_retry_runner_reads_only_due_devices(self) -> None:
        read_meter(
            self.device, _TimeoutReader(), now=self.t0, retry_policy=self.policy
        )
        self.assertEqual(
            run_due_retries(
                _SuccessfulReader(),
                now=self.t0 + timedelta(seconds=30),
                retry_policy=self.policy,
            ),
            [],
        )
        logs = run_due_retries(
            _SuccessfulReader(),
            now=self.t0 + timedelta(minutes=1),
            retry_policy=self.policy,
        )
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].status, MeterReadingLog.Status.RECOVERED)

    def test_history_is_append_only(self) -> None:
        log = read_meter(
            self.device, _SuccessfulReader(), now=self.t0, retry_policy=self.policy
        )
        with self.assertRaises(TypeError):
            log.delete()
        with self.assertRaises(TypeError):
            MeterReadingLog.objects.filter(pk=log.pk).update(retry_number=99)


class RecalculationApprovalRequestTests(TestCase):
    """Daha önce faturalandırılmış bir tarih aralığıyla ÇAKIŞAN yeni bir
    hesaplama talep edildiğinde, bu talebin doğrudan çalışmayıp admin
    paneline (`ApprovalRequest`) düştüğünü doğrular.

    İş kuralı: İstenen aralık, geçmiş bir `BillingRun`'ın penceresiyle
    (birebir aynı VEYA kısmen — tek bir ortak gün bile) çakışıyorsa,
    kullanıcı doğrudan hesaplayamaz; her deneme AYRI bir yeniden
    faturalandırma talebi oluşturur ve hesaplama ancak admin onayından
    sonra çalışır (bkz. `billing.services._overlapping_runs_exist`).
    Çakışma yoksa hesaplama doğrudan yapılır.
    """

    def setUp(self) -> None:
        self.user = User.objects.create_user(username="runner2", password="x")
        self.complex = ApartmentComplex.objects.create(name="Tekrar Hesap Sitesi")
        ComplexAccess.objects.create(user=self.user, complex=self.complex)
        self.apartment = Apartment.objects.create(
            complex=self.complex, unit_no="1", area_m2=Decimal("100.00")
        )
        self.window_start = date(2026, 3, 1)
        self.window_end = date(2026, 3, 31)

    def _run(self, total_bill: float):
        return run_billing_or_request_approval(
            complex_id=self.complex.id,
            user=self.user,
            window_start=self.window_start,
            window_end=self.window_end,
            total_bill=total_bill,
            manual_energy={self.apartment.id: (0.0, 10.0)},
        )

    def test_first_run_succeeds_without_approval(self) -> None:
        billing_run, summary = self._run(1000.0)
        self.assertIsNotNone(billing_run.id)
        self.assertEqual(list_pending_approval_requests(), [])

    def test_recalculation_same_window_creates_pending_approval_request(self) -> None:
        """Aynı pencere için ikinci çalıştırma talebi doğrudan çalışmamalı,
        sessizce de reddedilmemeli — bir `ApprovalRequest` oluşturup admin
        paneline düşmelidir (birebir aynı pencere de bir çakışmadır)."""
        self._run(1000.0)

        with self.assertRaises(AdminApprovalRequiredError):
            self._run(2000.0)

        pending = list_pending_approval_requests()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].complex_id, self.complex.id)
        self.assertEqual(pending[0].period_year, self.window_start.year)
        self.assertEqual(pending[0].period_month, self.window_start.month)
        self.assertEqual(pending[0].requested_by_id, self.user.id)

    def test_after_admin_approval_recalculation_run_succeeds(self) -> None:
        first_run, _ = self._run(1000.0)

        with self.assertRaises(AdminApprovalRequiredError):
            self._run(2000.0)

        pending = list_pending_approval_requests()
        self.assertEqual(len(pending), 1)
        admin_user = User.objects.create_user(
            username="admin_approver", password="x", is_staff=True
        )
        approve_request(pending[0].id, admin_user)

        second_run, summary = self._run(2000.0)
        self.assertNotEqual(second_run.id, first_run.id)
        self.assertEqual(second_run.window_start_date, self.window_start)
        self.assertEqual(second_run.window_end_date, self.window_end)
        # Onay tek kullanımlıktır: bir sonraki talep tekrar onay ister.
        self.assertEqual(list_pending_approval_requests(), [])
        pending[0].refresh_from_db()
        self.assertEqual(pending[0].billing_run_id, second_run.id)

    def test_each_pending_retry_creates_a_separate_request(self) -> None:
        self._run(1000.0)

        with self.assertRaises(AdminApprovalRequiredError):
            self._run(2000.0)
        with self.assertRaises(AdminApprovalRequiredError):
            self._run(2000.0)

        requests = ApprovalRequest.objects.filter(
            complex=self.complex,
            window_start_date=self.window_start,
            window_end_date=self.window_end,
        ).order_by("requested_at", "id")
        self.assertEqual(requests.count(), 2)
        self.assertNotEqual(requests[0].id, requests[1].id)
        self.assertTrue(
            all(r.status == ApprovalRequest.Status.PENDING for r in requests)
        )

    def test_retry_after_denial_creates_a_new_request(self) -> None:
        self._run(1000.0)
        with self.assertRaises(AdminApprovalRequiredError):
            self._run(2000.0)

        first_request = list_pending_approval_requests()[0]
        admin_user = User.objects.create_user(
            username="admin_denier", password="x", is_staff=True
        )
        deny_request(first_request.id, admin_user)

        with self.assertRaises(AdminApprovalRequiredError):
            self._run(2000.0)

        first_request.refresh_from_db()
        requests = ApprovalRequest.objects.filter(
            complex=self.complex,
            window_start_date=self.window_start,
            window_end_date=self.window_end,
        ).order_by("requested_at", "id")
        self.assertEqual(requests.count(), 2)
        self.assertEqual(first_request.status, ApprovalRequest.Status.DENIED)
        self.assertEqual(requests[1].status, ApprovalRequest.Status.PENDING)

    def test_retry_after_consumed_approval_creates_a_new_request(self) -> None:
        self._run(1000.0)
        with self.assertRaises(AdminApprovalRequiredError):
            self._run(2000.0)

        approved = list_pending_approval_requests()[0]
        admin_user = User.objects.create_user(
            username="admin_once", password="x", is_staff=True
        )
        approve_request(approved.id, admin_user)
        second_run, _ = self._run(2000.0)

        with self.assertRaises(AdminApprovalRequiredError):
            self._run(3000.0)

        approved.refresh_from_db()
        self.assertEqual(approved.billing_run_id, second_run.id)
        requests = ApprovalRequest.objects.filter(
            complex=self.complex,
            window_start_date=self.window_start,
            window_end_date=self.window_end,
        )
        self.assertEqual(requests.count(), 2)
        self.assertEqual(
            requests.filter(status=ApprovalRequest.Status.PENDING).count(), 1
        )

    def test_first_run_of_another_non_overlapping_window_is_direct(self) -> None:
        """Aynı takvim ayındaki farklı ve çakışmayan ilk aralık, eski ay/yıl
        sayacı nedeniyle yanlışlıkla yeniden hesaplama sayılmamalıdır."""
        complex_obj = ApartmentComplex.objects.create(name="Aralık Bazlı Bina")
        ComplexAccess.objects.create(user=self.user, complex=complex_obj)
        apartment = Apartment.objects.create(
            complex=complex_obj, unit_no="2", area_m2=Decimal("100.00")
        )
        common = {
            "complex_id": complex_obj.id,
            "user": self.user,
            "total_bill": 500.0,
            "manual_energy": {apartment.id: (0.0, 10.0)},
        }
        run_billing_or_request_approval(
            window_start=date(2026, 3, 1),
            window_end=date(2026, 3, 10),
            **common,
        )

        run, _ = run_billing_or_request_approval(
            user=self.user,
            complex_id=complex_obj.id,
            window_start=date(2026, 3, 11),
            window_end=date(2026, 3, 20),
            total_bill=500.0,
            manual_energy={apartment.id: (0.0, 10.0)},
        )
        self.assertIsNotNone(run.id)

    def _run_window(self, window_start: date, window_end: date, total_bill: float):
        return run_billing_or_request_approval(
            complex_id=self.complex.id,
            user=self.user,
            window_start=window_start,
            window_end=window_end,
            total_bill=total_bill,
            manual_energy={self.apartment.id: (0.0, 10.0)},
        )

    def test_partial_overlap_creates_pending_request_instead_of_blocking(
        self,
    ) -> None:
        """Birebir aynı OLMAYAN ama kısmen çakışan bir pencere artık sert
        biçimde REDDEDİLMEZ — bir yeniden faturalandırma talebi oluşturup
        admin onayına yönlendirilir (iş kuralı gereği davranış değişti)."""
        self._run(1000.0)  # 2026-03-01 → 2026-03-31

        with self.assertRaises(AdminApprovalRequiredError):
            self._run_window(date(2026, 3, 15), date(2026, 4, 15), 1500.0)

        pending = list_pending_approval_requests()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].window_start_date, date(2026, 3, 15))
        self.assertEqual(pending[0].window_end_date, date(2026, 4, 15))
        self.assertEqual(pending[0].status, ApprovalRequest.Status.PENDING)

    def test_single_common_day_counts_as_overlap(self) -> None:
        """İki aralık arasında tek bir ORTAK GÜN bile olması çakışma
        sayılır: eski [01-10], yeni [10-20] → 10. gün ortaktır."""
        complex_obj = ApartmentComplex.objects.create(name="Tek Gün Sitesi")
        ComplexAccess.objects.create(user=self.user, complex=complex_obj)
        apartment = Apartment.objects.create(
            complex=complex_obj, unit_no="1", area_m2=Decimal("100.00")
        )
        common = {
            "complex_id": complex_obj.id,
            "user": self.user,
            "manual_energy": {apartment.id: (0.0, 10.0)},
        }
        run_billing_or_request_approval(
            window_start=date(2026, 5, 1), window_end=date(2026, 5, 10),
            total_bill=500.0, **common,
        )

        with self.assertRaises(AdminApprovalRequiredError):
            run_billing_or_request_approval(
                window_start=date(2026, 5, 10), window_end=date(2026, 5, 20),
                total_bill=600.0, **common,
            )
        self.assertEqual(len(list_pending_approval_requests()), 1)

    def test_new_window_containing_old_window_counts_as_overlap(self) -> None:
        """Eski dönem yeni dönemin İÇİNDE kalıyorsa çakışmadır."""
        self._run(1000.0)  # eski: 03-01 → 03-31

        with self.assertRaises(AdminApprovalRequiredError):
            # yeni [02-01 → 04-30] eskiyi tamamen kapsıyor
            self._run_window(date(2026, 2, 1), date(2026, 4, 30), 1500.0)
        self.assertEqual(len(list_pending_approval_requests()), 1)

    def test_new_window_inside_old_window_counts_as_overlap(self) -> None:
        """Yeni dönem eski dönemin İÇİNDE kalıyorsa çakışmadır."""
        self._run(1000.0)  # eski: 03-01 → 03-31

        with self.assertRaises(AdminApprovalRequiredError):
            # yeni [03-10 → 03-20] eskinin içinde
            self._run_window(date(2026, 3, 10), date(2026, 3, 20), 1500.0)
        self.assertEqual(len(list_pending_approval_requests()), 1)

    def test_partial_overlap_runs_after_admin_approval(self) -> None:
        """Kısmen çakışan bir aralık, admin onayından sonra çalışabilir ve
        ESKİ faturalandırma kaydı korunarak YENİ bir kayıt oluşturur."""
        first_run, _ = self._run(1000.0)  # 03-01 → 03-31

        with self.assertRaises(AdminApprovalRequiredError):
            self._run_window(date(2026, 3, 15), date(2026, 4, 15), 1500.0)

        pending = list_pending_approval_requests()
        admin_user = User.objects.create_user(
            username="admin_overlap", password="x", is_staff=True
        )
        approve_request(pending[0].id, admin_user)

        second_run, _ = self._run_window(
            date(2026, 3, 15), date(2026, 4, 15), 1500.0
        )
        self.assertNotEqual(second_run.id, first_run.id)
        # Eski kayıt SİLİNMEDİ / DEĞİŞMEDİ — geçmiş korunur.
        first_run.refresh_from_db()
        self.assertEqual(first_run.window_start_date, date(2026, 3, 1))
        self.assertEqual(first_run.window_end_date, date(2026, 3, 31))
        self.assertEqual(BillingRun.objects.filter(complex=self.complex).count(), 2)

    def test_denied_overlap_lets_user_create_a_new_request(self) -> None:
        """Reddedilmiş bir çakışma dönemi için kullanıcı YENİDEN talep
        oluşturabilir; her deneme ayrı kayıttır."""
        self._run(1000.0)

        with self.assertRaises(AdminApprovalRequiredError):
            self._run_window(date(2026, 3, 15), date(2026, 4, 15), 1500.0)
        first = list_pending_approval_requests()[0]
        admin_user = User.objects.create_user(
            username="admin_deny_overlap", password="x", is_staff=True
        )
        deny_request(first.id, admin_user)

        with self.assertRaises(AdminApprovalRequiredError):
            self._run_window(date(2026, 3, 15), date(2026, 4, 15), 1500.0)

        first.refresh_from_db()
        self.assertEqual(first.status, ApprovalRequest.Status.DENIED)
        requests = ApprovalRequest.objects.filter(
            complex=self.complex,
            window_start_date=date(2026, 3, 15),
            window_end_date=date(2026, 4, 15),
        )
        self.assertEqual(requests.count(), 2)
        self.assertEqual(
            requests.filter(status=ApprovalRequest.Status.PENDING).count(), 1
        )
