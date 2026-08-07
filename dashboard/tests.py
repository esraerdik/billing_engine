"""
tests.py (dashboard)
----------------------
Daire yönetiminin admin panelinden USER paneline taşınmasını doğrular:

    - Admin panelinde artık daire ekleme/düzenleme/silme YOKTUR; admin bu
      uç noktalara erişemez (kendi paneline yönlendirilir).
    - "user" rollü kullanıcı, YALNIZCA kendisine atanmış (ComplexAccess)
      binalarda daire yönetebilir.
    - Yetki kontrolü SUNUCU tarafında yapılır: yetkisiz kullanıcı URL
      üzerinden istek gönderse bile işlem yapamaz (arayüzden gizlemek
      yeterli değildir).
"""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.models import UserProfile
from django.utils import timezone

from billing.models import (
    Apartment,
    ApartmentComplex,
    BillingRun,
    ComplexAccess,
    MeterAlert,
    MeterDevice,
    MeterReadingLog,
)
from audit.models import AuditLog


class UiFeedbackInterfaceTests(TestCase):
    def setUp(self) -> None:
        self.admin = User.objects.create_user(
            username="ui_feedback_admin",
            password="secret",
            is_staff=True,
            is_superuser=True,
        )
        UserProfile.objects.update_or_create(
            user=self.admin,
            defaults={"role": UserProfile.Role.ADMIN},
        )
        self.complex = ApartmentComplex.objects.create(
            name="Modal Test Binası",
            address="Adres",
        )
        self.client.force_login(self.admin)

    def test_django_success_and_error_messages_render_as_global_toasts(self):
        error_response = self.client.post(
            reverse("add_complex"),
            {"name": "", "address": ""},
            follow=True,
        )
        self.assertContains(error_response, "Bina adı boş olamaz.")
        self.assertContains(error_response, "data-app-toast")
        self.assertContains(error_response, "app-toast--error")
        self.assertContains(error_response, "field-name")

        success_response = self.client.post(
            reverse("add_complex"),
            {"name": "Toast Başarı Binası", "address": ""},
            follow=True,
        )
        self.assertContains(success_response, "Toast Başarı Binası")
        self.assertContains(success_response, "data-app-toast")
        self.assertContains(success_response, "app-toast--success")

    def test_delete_forms_use_shared_confirmation_modal(self):
        response = self.client.get(reverse("admin_dashboard"))

        self.assertContains(response, "data-confirm-modal")
        self.assertContains(response, "data-confirm-form")
        self.assertContains(response, 'data-confirm-title="Silme Onayı"')
        self.assertContains(response, 'data-confirm-label="Evet, Sil"')
        self.assertNotContains(response, "return confirm(")
        self.assertContains(response, "ui_feedback.js")

    def test_restore_forms_reuse_confirmation_modal_with_success_variant(self):
        self.complex.mark_deleted(deleted_by=self.admin)

        response = self.client.get(reverse("deleted_complexes"))

        self.assertContains(response, "Geri Yükleme Onayı")
        self.assertContains(response, 'data-confirm-label="Evet, Geri Yükle"')
        self.assertContains(response, 'data-confirm-variant="success"')


class UserManagementSecurityInterfaceTests(TestCase):
    def setUp(self) -> None:
        User.objects.update(is_active=False, is_staff=False, is_superuser=False)
        UserProfile.objects.update(role=UserProfile.Role.USER)
        self.admin = User.objects.create_user(
            username="security_admin",
            password="secret",
            is_staff=True,
            is_superuser=True,
        )
        UserProfile.objects.update_or_create(
            user=self.admin, defaults={"role": UserProfile.Role.ADMIN}
        )
        self.user = User.objects.create_user(
            username="managed_user", password="secret"
        )
        self.client.force_login(self.admin)

    def test_list_has_no_quick_activation_buttons(self) -> None:
        response = self.client.get(reverse("admin_dashboard"))
        content = response.content.decode("utf-8")
        self.assertNotIn("Pasifleştir", content)
        self.assertNotIn("Aktifleştir", content)
        self.assertNotIn("toggle-active", content)
        self.assertContains(response, reverse("edit_user", args=[self.user.id]))
        self.assertContains(response, reverse("delete_user", args=[self.user.id]))

    def test_user_can_only_be_deactivated_and_activated_from_edit_page(self) -> None:
        edit_url = reverse("edit_user", args=[self.user.id])
        self.assertContains(self.client.get(edit_url), 'name="is_active"')

        response = self.client.post(
            edit_url,
            {
                "username": self.user.username,
                "role": UserProfile.Role.USER,
                "complex_ids": [],
            },
        )
        self.assertRedirects(response, reverse("admin_dashboard"))
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.assertTrue(
            AuditLog.objects.filter(
                action="user_deactivated",
                object_id=str(self.user.id),
                success=True,
            ).exists()
        )

        response = self.client.post(
            edit_url,
            {
                "username": self.user.username,
                "role": UserProfile.Role.USER,
                "is_active": "on",
                "complex_ids": [],
            },
        )
        self.assertRedirects(response, reverse("admin_dashboard"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.assertTrue(
            AuditLog.objects.filter(
                action="user_activated",
                object_id=str(self.user.id),
                success=True,
            ).exists()
        )

    def test_admin_edit_page_has_no_active_checkbox(self) -> None:
        response = self.client.get(reverse("edit_user", args=[self.admin.id]))
        self.assertNotContains(response, 'type="checkbox" name="is_active"')

    def test_two_admins_allow_one_deletion_and_audit_it(self) -> None:
        second_admin = User.objects.create_user(
            username="security_admin_2",
            password="secret",
            is_staff=True,
            is_superuser=True,
        )
        UserProfile.objects.update_or_create(
            user=second_admin, defaults={"role": UserProfile.Role.ADMIN}
        )
        response = self.client.post(reverse("delete_user", args=[second_admin.id]))
        self.assertRedirects(response, reverse("admin_dashboard"))
        second_admin.refresh_from_db()
        self.assertTrue(second_admin.profile.is_deleted)
        self.assertFalse(second_admin.is_active)
        self.assertTrue(
            AuditLog.objects.filter(
                action="admin_deleted",
                object_id=str(second_admin.id),
                success=True,
            ).exists()
        )

    def test_user_delete_is_soft_delete_hidden_and_audited(self) -> None:
        response = self.client.post(reverse("delete_user", args=[self.user.id]))
        self.assertRedirects(response, reverse("admin_dashboard"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.profile.is_deleted)
        self.assertFalse(self.user.is_active)
        self.assertNotContains(
            self.client.get(reverse("admin_dashboard")),
            self.user.username,
        )
        self.assertTrue(
            AuditLog.objects.filter(
                action="user_soft_deleted",
                object_id=str(self.user.id),
                description__contains="Kullanıcı Soft Delete ile silindi.",
                success=True,
            ).exists()
        )

    def test_deleted_user_screen_and_restore_work(self) -> None:
        self.client.post(reverse("delete_user", args=[self.user.id]))
        deleted_page = self.client.get(reverse("deleted_users"))
        self.assertContains(deleted_page, self.user.username)
        self.assertContains(deleted_page, "Geri Yükle")

        response = self.client.post(
            reverse("restore_deleted_user", args=[self.user.id])
        )
        self.assertRedirects(response, reverse("deleted_users"))
        self.user.refresh_from_db()
        self.assertFalse(self.user.profile.is_deleted)
        self.assertTrue(self.user.is_active)
        self.assertIn(
            self.user.id,
            [u.id for u in self.client.get(reverse("admin_dashboard")).context["users"]],
        )
        self.assertTrue(
            AuditLog.objects.filter(
                action="user_restored",
                object_id=str(self.user.id),
                success=True,
            ).exists()
        )
        self.client.logout()
        self.assertTrue(
            self.client.login(username=self.user.username, password="secret")
        )

    def test_single_admin_self_deletion_is_blocked_and_audited(self) -> None:
        response = self.client.post(reverse("delete_user", args=[self.admin.id]))
        self.assertRedirects(response, reverse("admin_dashboard"))
        self.assertTrue(User.objects.filter(pk=self.admin.id).exists())
        self.assertTrue(
            AuditLog.objects.filter(
                action="admin_deletion_blocked",
                object_id=str(self.admin.id),
                success=False,
            ).exists()
        )


class ComplexSoftDeleteInterfaceTests(TestCase):
    def setUp(self) -> None:
        self.admin = User.objects.create_user(
            username="complex_soft_admin",
            password="secret",
            is_staff=True,
            is_superuser=True,
        )
        UserProfile.objects.update_or_create(
            user=self.admin, defaults={"role": UserProfile.Role.ADMIN}
        )
        self.complex = ApartmentComplex.objects.create(
            name="Bağlı Kayıtlı Apartman", address="Adres"
        )
        self.apartment = Apartment.objects.create(
            complex=self.complex, unit_no="10", area_m2=Decimal("80.00")
        )
        self.billing_run = BillingRun.objects.create(
            complex=self.complex,
            period_year=2026,
            period_month=8,
            window_start_date="2026-08-01",
            window_end_date="2026-08-31",
            total_bill="1000.00",
            total_fixed_amount="300.00",
            total_consumption_amount="700.00",
            total_area="80.00",
            total_energy="25.0000",
            run_by=self.admin,
        )
        self.client.force_login(self.admin)

    def test_linked_complex_is_soft_deleted_and_restored_with_history(self) -> None:
        response = self.client.post(
            reverse("delete_complex", args=[self.complex.id])
        )
        self.assertRedirects(response, reverse("admin_dashboard"))
        self.complex.refresh_from_db()
        self.assertTrue(self.complex.is_deleted)
        self.assertEqual(self.complex.deleted_by_id, self.admin.id)
        self.assertTrue(Apartment.objects.filter(pk=self.apartment.id).exists())
        self.assertTrue(BillingRun.objects.filter(pk=self.billing_run.id).exists())
        active_ids = {
            c.id
            for c in self.client.get(reverse("admin_dashboard")).context["complexes"]
        }
        self.assertNotIn(self.complex.id, active_ids)
        self.assertTrue(
            AuditLog.objects.filter(
                action="complex_soft_deleted",
                object_id=str(self.complex.id),
                success=True,
            ).exists()
        )

        deleted_page = self.client.get(reverse("deleted_complexes"))
        self.assertContains(deleted_page, self.complex.name)
        self.assertContains(deleted_page, "Geri Yükle")
        response = self.client.post(
            reverse("restore_deleted_complex", args=[self.complex.id])
        )
        self.assertRedirects(response, reverse("deleted_complexes"))
        self.complex.refresh_from_db()
        self.assertFalse(self.complex.is_deleted)
        self.assertIsNone(self.complex.deleted_at)
        self.assertTrue(
            AuditLog.objects.filter(
                action="complex_restored",
                object_id=str(self.complex.id),
                success=True,
            ).exists()
        )
        restored_ids = {
            c.id
            for c in self.client.get(reverse("admin_dashboard")).context["complexes"]
        }
        self.assertIn(self.complex.id, restored_ids)

class ComplexEditInterfaceTests(TestCase):
    def setUp(self) -> None:
        self.admin = User.objects.create_user(
            username="complex_admin", password="secret"
        )
        UserProfile.objects.update_or_create(
            user=self.admin, defaults={"role": UserProfile.Role.ADMIN}
        )
        self.complex = ApartmentComplex.objects.create(
            name="Eski Bina", address="Eski Adres"
        )
        self.client.force_login(self.admin)

    def test_admin_list_has_link_without_inline_edit_fields(self) -> None:
        response = self.client.get(reverse("admin_dashboard"))
        content = response.content.decode("utf-8")
        self.assertContains(response, reverse("edit_complex", args=[self.complex.id]))
        self.assertNotIn(
            f'name="name" value="{self.complex.name}"',
            content,
        )

    def test_edit_button_opens_separate_page(self) -> None:
        response = self.client.get(
            reverse("edit_complex", args=[self.complex.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard/complex_edit.html")
        self.assertContains(response, self.complex.name)
        self.assertContains(response, self.complex.address)

    def test_save_updates_complex_and_creates_audit_log(self) -> None:
        response = self.client.post(
            reverse("edit_complex", args=[self.complex.id]),
            {"name": "Yeni Bina", "address": "Yeni Adres"},
        )
        self.assertRedirects(response, reverse("admin_dashboard"))
        self.complex.refresh_from_db()
        self.assertEqual(self.complex.name, "Yeni Bina")
        self.assertEqual(self.complex.address, "Yeni Adres")
        self.assertTrue(
            AuditLog.objects.filter(
                action="complex_update",
                category=AuditLog.Category.COMPLEX,
                user=self.admin,
                object_id=str(self.complex.id),
                object_repr="Yeni Bina",
                success=True,
            ).exists()
        )


class MeterReadingHistoryInterfaceTests(TestCase):
    def setUp(self) -> None:
        self.admin = User.objects.create_user(username="meter_admin", password="x")
        UserProfile.objects.update_or_create(
            user=self.admin, defaults={"role": UserProfile.Role.ADMIN}
        )
        self.user = User.objects.create_user(username="meter_user", password="x")
        self.complex = ApartmentComplex.objects.create(name="Sayaç Binası")
        ComplexAccess.objects.create(user=self.user, complex=self.complex)
        self.apartment = Apartment.objects.create(
            complex=self.complex, unit_no="203", area_m2=Decimal("70.00")
        )
        self.device = MeterDevice.objects.create(
            apartment=self.apartment,
            modbus_address="device-203",
            installed_at=timezone.now(),
        )
        self.log = MeterReadingLog.objects.create(
            device=self.device,
            complex=self.complex,
            apartment=self.apartment,
            read_at=timezone.now(),
            status=MeterReadingLog.Status.FAILED,
            retry_number=2,
            error_type=MeterReadingLog.ErrorType.TIMEOUT,
            error_description="Timeout",
            device_identifier=self.device.modbus_address,
        )
        self.alert = MeterAlert.objects.create(
            device=self.device,
            severity=MeterAlert.Severity.WARNING,
            message="Daire 203 sayaç verisi alınamadı.",
        )

    def test_admin_can_open_and_filter_history(self) -> None:
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("meter_reading_history"),
            {"complex": self.complex.id, "status": MeterReadingLog.Status.FAILED},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sayaç Okuma Geçmişi")
        self.assertContains(response, "device-203")
        self.assertContains(response, "Timeout")

    def test_regular_user_cannot_open_admin_history(self) -> None:
        self.client.force_login(self.user)
        response = self.client.get(reverse("meter_reading_history"))
        self.assertEqual(response.status_code, 302)

    def test_admin_and_authorized_user_see_active_alert(self) -> None:
        self.client.force_login(self.admin)
        self.assertContains(
            self.client.get(reverse("admin_dashboard")),
            "Daire 203 sayaç verisi alınamadı.",
        )
        self.client.force_login(self.user)
        self.assertContains(
            self.client.get(
                f"{reverse('user_dashboard')}?complex_id={self.complex.id}"
            ),
            "Daire 203 sayaç verisi alınamadı.",
        )


class AdminPanelHasNoApartmentManagementTests(TestCase):
    """Admin paneli yalnızca bina/kullanıcı/onay yönetimi içerir; daire
    yönetimi tamamen kaldırılmıştır ve admin bu uç noktalara erişemez."""

    def setUp(self) -> None:
        self.admin = User.objects.create_user(username="admin_ui", password="x")
        UserProfile.objects.update_or_create(
            user=self.admin, defaults={"role": UserProfile.Role.ADMIN}
        )
        self.client.force_login(self.admin)
        self.complex = ApartmentComplex.objects.create(name="Admin Test Binası")
        self.apartment = Apartment.objects.create(
            complex=self.complex, unit_no="A-1", area_m2=Decimal("50.00")
        )

    def test_admin_dashboard_has_no_apartment_add_form(self) -> None:
        resp = self.client.get(reverse("admin_dashboard"))
        content = resp.content.decode("utf-8")
        self.assertNotIn("Daire Ekle", content)
        self.assertNotIn(reverse("add_apartment"), content)

    def test_admin_cannot_add_apartment(self) -> None:
        resp = self.client.post(
            reverse("add_apartment"),
            data={"complex_id": self.complex.id, "unit_no": "YENI", "area_m2": "42.00"},
        )
        # Admin, daire uç noktalarından kendi paneline yönlendirilir.
        self.assertRedirects(resp, reverse("admin_dashboard"))
        self.assertFalse(Apartment.objects.filter(unit_no="YENI").exists())

    def test_admin_cannot_open_apartment_edit(self) -> None:
        resp = self.client.get(
            reverse("edit_apartment", args=[self.apartment.id])
        )
        self.assertRedirects(resp, reverse("admin_dashboard"))

    def test_admin_dashboard_has_no_site_wording(self) -> None:
        resp = self.client.get(reverse("admin_dashboard"))
        content = resp.content.decode("utf-8")
        self.assertNotIn("Site", content)
        self.assertNotIn("site", content)


class UserPanelApartmentManagementTests(TestCase):
    """Yetkili "user", kendisine atanmış binada daireleri listeleyip
    ekleyip düzenleyip silebilir."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(username="uyeli", password="x")
        # create_user sinyali varsayılan USER profili açar; yine de garanti edelim.
        UserProfile.objects.update_or_create(
            user=self.user, defaults={"role": UserProfile.Role.USER}
        )
        self.complex = ApartmentComplex.objects.create(name="Üye Binası")
        ComplexAccess.objects.create(user=self.user, complex=self.complex)
        self.apartment = Apartment.objects.create(
            complex=self.complex,
            unit_no="U-1",
            area_m2=Decimal("50.00"),
            block="B Blok",
        )
        self.client.force_login(self.user)

    def test_user_dashboard_shows_apartment_management(self) -> None:
        resp = self.client.get(
            f"{reverse('user_dashboard')}?complex_id={self.complex.id}"
        )
        content = resp.content.decode("utf-8")
        self.assertIn("Daire Yönetimi", content)
        self.assertIn("U-1", content)
        self.assertIn(reverse("add_apartment"), content)

    def test_user_can_add_apartment_to_accessible_complex(self) -> None:
        resp = self.client.post(
            reverse("add_apartment"),
            data={"complex_id": self.complex.id, "unit_no": "U-2", "area_m2": "70.00"},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            Apartment.objects.filter(complex=self.complex, unit_no="U-2").exists()
        )

    def test_user_can_open_and_submit_edit_preserving_block(self) -> None:
        edit_url = reverse("edit_apartment", args=[self.apartment.id])
        get_resp = self.client.get(edit_url)
        self.assertEqual(get_resp.status_code, 200)
        # Blok değeri gizli alanda korunmalı (arayüzden kaldırıldı ama silinmez).
        self.assertIn('name="block" value="B Blok"', get_resp.content.decode("utf-8"))

        self.client.post(
            edit_url,
            data={
                "complex_id": self.complex.id,
                "unit_no": "U-1",
                "block": "B Blok",
                "area_m2": "55.00",
                "resident_name": "",
                "is_active": "on",
            },
        )
        self.apartment.refresh_from_db()
        self.assertEqual(self.apartment.area_m2, Decimal("55.00"))
        self.assertEqual(self.apartment.block, "B Blok")

    def test_user_can_delete_apartment(self) -> None:
        resp = self.client.post(
            reverse("delete_apartment", args=[self.apartment.id])
        )
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Apartment.objects.filter(pk=self.apartment.id).exists())


class ApartmentAuthorizationTests(TestCase):
    """Sunucu tarafı yetkilendirme: "user", yetkisi OLMAYAN bir binanın
    dairelerini göremez ve üzerinde işlem yapamaz — URL doğrudan çağrılsa
    bile."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(username="kisitli", password="x")
        UserProfile.objects.update_or_create(
            user=self.user, defaults={"role": UserProfile.Role.USER}
        )
        # Kullanıcı yalnızca A binasına erişimli; B binasına erişimi YOK.
        self.complex_a = ApartmentComplex.objects.create(name="Erişimli Bina")
        self.complex_b = ApartmentComplex.objects.create(name="Yasak Bina")
        ComplexAccess.objects.create(user=self.user, complex=self.complex_a)
        self.apt_b = Apartment.objects.create(
            complex=self.complex_b, unit_no="B-1", area_m2=Decimal("60.00")
        )
        self.client.force_login(self.user)

    def test_cannot_add_apartment_to_unauthorized_complex(self) -> None:
        self.client.post(
            reverse("add_apartment"),
            data={"complex_id": self.complex_b.id, "unit_no": "HACK", "area_m2": "10.00"},
        )
        self.assertFalse(
            Apartment.objects.filter(complex=self.complex_b, unit_no="HACK").exists()
        )

    def test_cannot_open_edit_of_unauthorized_apartment(self) -> None:
        resp = self.client.get(reverse("edit_apartment", args=[self.apt_b.id]))
        self.assertEqual(resp.status_code, 404)

    def test_cannot_submit_edit_of_unauthorized_apartment(self) -> None:
        resp = self.client.post(
            reverse("edit_apartment", args=[self.apt_b.id]),
            data={
                "complex_id": self.complex_b.id,
                "unit_no": "DEGISTI",
                "area_m2": "99.00",
                "is_active": "on",
            },
        )
        self.assertEqual(resp.status_code, 404)
        self.apt_b.refresh_from_db()
        self.assertEqual(self.apt_b.unit_no, "B-1")

    def test_cannot_delete_unauthorized_apartment(self) -> None:
        resp = self.client.post(reverse("delete_apartment", args=[self.apt_b.id]))
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(Apartment.objects.filter(pk=self.apt_b.id).exists())

    def test_cannot_move_apartment_into_unauthorized_complex(self) -> None:
        """Erişimli binadaki bir daire, erişimsiz bir binaya TAŞINAMAZ."""
        apt_a = Apartment.objects.create(
            complex=self.complex_a, unit_no="A-1", area_m2=Decimal("40.00")
        )
        self.client.post(
            reverse("edit_apartment", args=[apt_a.id]),
            data={
                "complex_id": self.complex_b.id,  # yasak hedef
                "unit_no": "A-1",
                "area_m2": "40.00",
                "is_active": "on",
            },
        )
        apt_a.refresh_from_db()
        self.assertEqual(apt_a.complex_id, self.complex_a.id)
