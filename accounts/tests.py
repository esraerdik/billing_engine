from __future__ import annotations

from django.contrib.auth.models import User
from django.test import TestCase

from audit.models import AuditLog
from audit.services import record_audit
from billing.models import ApartmentComplex, BillingRun, ComplexAccess
from billing.services import list_accessible_complexes

from .exceptions import (
    AdminDeactivationForbiddenError,
    LastActiveAdminError,
    LastAdminDeletionError,
)
from .models import UserProfile
from .services import (
    create_user,
    delete_user,
    list_users,
    set_user_active,
    update_user,
)


class AdminActivationProtectionTests(TestCase):
    def setUp(self) -> None:
        User.objects.update(is_active=False, is_staff=False, is_superuser=False)
        UserProfile.objects.update(role=UserProfile.Role.USER)
        self.admin = create_user(
            username="admin_one",
            password="secret",
            role=UserProfile.Role.ADMIN,
        )

    def test_admin_cannot_be_deactivated_even_when_another_admin_exists(self) -> None:
        create_user(
            username="admin_two",
            password="secret",
            role=UserProfile.Role.ADMIN,
        )
        with self.assertRaises(AdminDeactivationForbiddenError):
            set_user_active(self.admin.id, False)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_admin_cannot_be_deactivated_through_edit_service(self) -> None:
        with self.assertRaises(AdminDeactivationForbiddenError):
            update_user(
                user_id=self.admin.id,
                username=self.admin.username,
                role=UserProfile.Role.ADMIN,
                is_active=False,
            )
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_regular_user_can_be_deactivated_and_activated(self) -> None:
        user = create_user(
            username="regular",
            password="secret",
            role=UserProfile.Role.USER,
        )
        self.assertFalse(set_user_active(user.id, False).is_active)
        self.assertTrue(set_user_active(user.id, True).is_active)

    def test_last_admin_cannot_be_demoted(self) -> None:
        with self.assertRaises(LastActiveAdminError):
            update_user(
                user_id=self.admin.id,
                username=self.admin.username,
                role=UserProfile.Role.USER,
                is_active=True,
            )

    def test_legacy_inactive_admin_can_be_reactivated_and_log_in(self) -> None:
        self.admin.is_active = False
        self.admin.save(update_fields=["is_active"])
        set_user_active(self.admin.id, True)
        self.assertTrue(self.client.login(username="admin_one", password="secret"))


class AdminDeletionProtectionTests(TestCase):
    def setUp(self) -> None:
        User.objects.update(is_active=False, is_staff=False, is_superuser=False)
        UserProfile.objects.update(role=UserProfile.Role.USER)
        self.admin = create_user(
            username="admin_one",
            password="secret",
            role=UserProfile.Role.ADMIN,
        )

    def test_single_admin_cannot_be_deleted(self) -> None:
        with self.assertRaises(LastAdminDeletionError):
            delete_user(self.admin.id)
        self.assertTrue(User.objects.filter(pk=self.admin.id).exists())

    def test_one_of_two_admins_can_be_deleted(self) -> None:
        second_admin = create_user(
            username="admin_two",
            password="secret",
            role=UserProfile.Role.ADMIN,
        )
        delete_user(second_admin.id)
        second_admin.refresh_from_db()
        self.assertFalse(second_admin.is_active)
        self.assertTrue(second_admin.profile.is_deleted)
        self.assertTrue(
            User.objects.filter(pk=self.admin.id, is_active=True).exists()
        )

    def test_admin_with_existing_audit_history_can_be_deleted(self) -> None:
        second_admin = create_user(
            username="admin_two",
            password="secret",
            role=UserProfile.Role.ADMIN,
        )
        log = record_audit(
            action="historical_action",
            category=AuditLog.Category.USER,
            user=second_admin,
            object_type="User",
            object_id=second_admin.id,
            object_repr=second_admin.username,
        )
        delete_user(second_admin.id)
        log.refresh_from_db()
        self.assertEqual(log.user_id, second_admin.id)
        self.assertEqual(log.username, "admin_two")

    def test_last_admin_is_protected_after_other_admin_is_deleted(self) -> None:
        second_admin = create_user(
            username="admin_two",
            password="secret",
            role=UserProfile.Role.ADMIN,
        )
        delete_user(second_admin.id)
        with self.assertRaises(LastAdminDeletionError):
            delete_user(self.admin.id)

    def test_regular_user_is_soft_deleted_and_hidden_from_default_list(self) -> None:
        user = create_user(
            username="regular",
            password="secret",
            role=UserProfile.Role.USER,
        )
        deleted = delete_user(user.id, deleted_by=self.admin)
        deleted.refresh_from_db()
        self.assertTrue(User.objects.filter(pk=user.id).exists())
        self.assertFalse(deleted.is_active)
        self.assertTrue(deleted.profile.is_deleted)
        self.assertIsNotNone(deleted.profile.deleted_at)
        self.assertEqual(deleted.profile.deleted_by_id, self.admin.id)
        self.assertNotIn(user.id, [item.id for item in list_users()])
        self.assertIn(
            user.id, [item.id for item in list_users(include_deleted=True)]
        )
        self.assertFalse(
            self.client.login(username="regular", password="secret")
        )

    def test_user_with_billing_history_is_soft_deleted_without_data_loss(self) -> None:
        user = create_user(
            username="billing_user",
            password="secret",
            role=UserProfile.Role.USER,
        )
        complex_obj = ApartmentComplex.objects.create(name="Geçmiş Binası")
        billing_run = BillingRun.objects.create(
            complex=complex_obj,
            period_year=2026,
            period_month=8,
            window_start_date="2026-08-01",
            window_end_date="2026-08-31",
            total_bill="1000.00",
            total_fixed_amount="300.00",
            total_consumption_amount="700.00",
            total_area="100.00",
            total_energy="50.0000",
            run_by=user,
        )
        log = record_audit(
            action="billing_history",
            category=AuditLog.Category.BILLING,
            user=user,
            object_type="BillingRun",
            object_id=billing_run.id,
        )

        delete_user(user.id, deleted_by=self.admin)

        billing_run.refresh_from_db()
        log.refresh_from_db()
        self.assertEqual(billing_run.run_by_id, user.id)
        self.assertEqual(log.user_id, user.id)
        self.assertTrue(User.objects.get(pk=user.id).profile.is_deleted)

    def test_soft_deleted_user_has_no_complex_access(self) -> None:
        user = create_user(
            username="access_user",
            password="secret",
            role=UserProfile.Role.USER,
        )
        complex_obj = ApartmentComplex.objects.create(name="Yetkili Bina")
        ComplexAccess.objects.create(user=user, complex=complex_obj)
        delete_user(user.id, deleted_by=self.admin)
        user.refresh_from_db()
        self.assertEqual(list_accessible_complexes(user), [])
