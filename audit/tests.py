from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.models import UserProfile
from billing.models import Apartment, ApartmentComplex

from .labels import UNKNOWN_ACTION_LABEL, get_action_label
from .models import AuditLog


class AuditLogTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="audit_admin", password="secret")
        UserProfile.objects.update_or_create(
            user=self.admin, defaults={"role": UserProfile.Role.ADMIN}
        )
        self.user = User.objects.create_user(username="audit_user", password="secret")

    def test_login_success_failure_and_logout_are_logged(self):
        self.client.post(reverse("login"), {"username": "audit_user", "password": "wrong"})
        self.assertTrue(AuditLog.objects.filter(action="login_failed", success=False).exists())
        self.client.post(reverse("login"), {"username": "audit_user", "password": "secret"})
        self.assertTrue(AuditLog.objects.filter(action="login_success", user=self.user).exists())
        self.client.get(reverse("logout"))
        self.assertTrue(AuditLog.objects.filter(action="logout", user=self.user).exists())

    def test_only_admin_can_view_log_page(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("audit_logs"))
        self.assertEqual(response.status_code, 302)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("audit_logs")).status_code, 200)

    def test_log_cannot_be_changed_or_deleted(self):
        log = AuditLog.objects.create(
            action="test", category=AuditLog.Category.SYSTEM, description="append only"
        )
        log.description = "changed"
        with self.assertRaises(TypeError):
            log.save()
        with self.assertRaises(TypeError):
            log.delete()
        with self.assertRaises(TypeError):
            AuditLog.objects.filter(pk=log.pk).update(description="changed")
        with self.assertRaises(TypeError):
            AuditLog.objects.filter(pk=log.pk).delete()

    def test_pagination_links_keep_filters_without_duplicate_page_parameter(self):
        self.client.force_login(self.admin)
        AuditLog.objects.bulk_create(
            [
                AuditLog(
                    action="pagination_test",
                    category=AuditLog.Category.SYSTEM,
                    description=f"Kayıt {index}",
                )
                for index in range(120)
            ]
        )

        second_page = self.client.get(
            reverse("audit_logs"),
            {"action": "pagination_test", "page": "2"},
        )
        self.assertEqual(second_page.context["page"].number, 2)
        self.assertContains(
            second_page,
            "?action=pagination_test&amp;page=1",
        )
        self.assertNotContains(second_page, "page=1&amp;page=2")
        self.assertNotContains(second_page, ">Önceki<")
        self.assertNotContains(second_page, ">Sonraki<")
        self.assertContains(second_page, 'aria-label="İlk sayfa"')
        self.assertContains(second_page, 'aria-label="Son sayfa"')

        first_page = self.client.get(
            reverse("audit_logs"),
            {"action": "pagination_test", "page": "1"},
        )
        last_page = self.client.get(
            reverse("audit_logs"),
            {"action": "pagination_test", "page": "3"},
        )
        self.assertEqual(first_page.context["page"].number, 1)
        self.assertEqual(last_page.context["page"].number, 3)
        self.assertFalse(first_page.context["page"].has_previous())
        self.assertFalse(last_page.context["page"].has_next())

    def test_logs_can_be_filtered_by_complex(self):
        self.client.force_login(self.admin)
        selected_complex = ApartmentComplex.objects.create(name="Filtre Binası")
        other_complex = ApartmentComplex.objects.create(name="Diğer Bina")
        selected_apartment = Apartment.objects.create(
            complex=selected_complex,
            unit_no="101",
            area_m2="80.00",
        )
        other_apartment = Apartment.objects.create(
            complex=other_complex,
            unit_no="202",
            area_m2="90.00",
        )
        selected_complex_log = AuditLog.objects.create(
            action="complex_update",
            category=AuditLog.Category.COMPLEX,
            object_type="ApartmentComplex",
            object_id=selected_complex.id,
            object_repr=selected_complex.name,
        )
        selected_apartment_log = AuditLog.objects.create(
            action="apartment_update",
            category=AuditLog.Category.APARTMENT,
            object_type="Apartment",
            object_id=selected_apartment.id,
            object_repr=str(selected_apartment),
        )
        selected_metadata_log = AuditLog.objects.create(
            action="meter_retry",
            category=AuditLog.Category.SYSTEM,
            object_type="MeterDevice",
            object_id="999",
            metadata={"complex_id": selected_complex.id},
        )
        AuditLog.objects.create(
            action="apartment_update",
            category=AuditLog.Category.APARTMENT,
            object_type="Apartment",
            object_id=other_apartment.id,
            object_repr=str(other_apartment),
        )

        response = self.client.get(
            reverse("audit_logs"),
            {"complex": str(selected_complex.id)},
        )

        self.assertEqual(response.status_code, 200)
        returned_ids = {log.id for log in response.context["page"].object_list}
        self.assertSetEqual(
            returned_ids,
            {
                selected_complex_log.id,
                selected_apartment_log.id,
                selected_metadata_log.id,
            },
        )
        self.assertContains(response, 'name="complex"')
        self.assertContains(
            response,
            (
                f'<option value="{selected_complex.id}" selected>'
                f"{selected_complex.name}</option>"
            ),
        )

    def test_action_codes_are_translated_only_in_the_interface(self):
        self.client.force_login(self.admin)
        successful_login = AuditLog.objects.create(
            action="login_success",
            category=AuditLog.Category.AUTHENTICATION,
        )
        AuditLog.objects.create(
            action="login_failed",
            category=AuditLog.Category.AUTHENTICATION,
            success=False,
        )

        response = self.client.get(
            reverse("audit_logs"),
            {"action": "login_success"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Başarılı Giriş")
        self.assertContains(response, "Başarısız Giriş")
        self.assertNotContains(response, ">login_success<")
        self.assertNotContains(response, ">login_failed<")
        returned_logs = list(response.context["page"].object_list)
        self.assertIn(successful_login.id, [log.id for log in returned_logs])
        self.assertTrue(all(log.action == "login_success" for log in returned_logs))
        successful_login.refresh_from_db()
        self.assertEqual(successful_login.action, "login_success")

    def test_equivalent_delete_actions_are_listed_and_filtered_once(self):
        self.client.force_login(self.admin)
        legacy_user_delete = AuditLog.objects.create(
            action="user_delete",
            category=AuditLog.Category.USER,
        )
        soft_user_delete = AuditLog.objects.create(
            action="user_soft_deleted",
            category=AuditLog.Category.USER,
        )
        legacy_complex_delete = AuditLog.objects.create(
            action="building_deleted",
            category=AuditLog.Category.COMPLEX,
        )
        soft_complex_delete = AuditLog.objects.create(
            action="complex_soft_deleted",
            category=AuditLog.Category.COMPLEX,
        )

        response = self.client.get(reverse("audit_logs"))
        action_labels = [label for _, label in response.context["actions"]]
        self.assertEqual(action_labels.count("Kullanıcı Silindi"), 1)
        self.assertEqual(action_labels.count("Apartman Silindi"), 1)

        user_response = self.client.get(
            reverse("audit_logs"),
            {"action": "user_soft_deleted"},
        )
        user_log_ids = {
            log.id for log in user_response.context["page"].object_list
        }
        self.assertSetEqual(
            user_log_ids,
            {legacy_user_delete.id, soft_user_delete.id},
        )
        self.assertEqual(user_response.context["selected_action"], "user_soft_deleted")

        legacy_url_response = self.client.get(
            reverse("audit_logs"),
            {"action": "user_delete"},
        )
        self.assertEqual(
            legacy_url_response.context["selected_action"],
            "user_soft_deleted",
        )
        self.assertSetEqual(
            {log.id for log in legacy_url_response.context["page"].object_list},
            {legacy_user_delete.id, soft_user_delete.id},
        )

        complex_response = self.client.get(
            reverse("audit_logs"),
            {"action": "complex_soft_deleted"},
        )
        self.assertSetEqual(
            {log.id for log in complex_response.context["page"].object_list},
            {legacy_complex_delete.id, soft_complex_delete.id},
        )

        for log, original_action in (
            (legacy_user_delete, "user_delete"),
            (soft_user_delete, "user_soft_deleted"),
            (legacy_complex_delete, "building_deleted"),
            (soft_complex_delete, "complex_soft_deleted"),
        ):
            log.refresh_from_db()
            self.assertEqual(log.action, original_action)

    def test_all_production_action_codes_have_turkish_labels(self):
        production_codes = {
            "login_success",
            "login_failed",
            "logout",
            "user_create",
            "user_update",
            "password_change",
            "user_activated",
            "user_deactivated",
            "user_delete",
            "user_soft_deleted",
            "user_restored",
            "admin_deleted",
            "admin_deletion_blocked",
            "admin_deactivation_blocked",
            "admin_reactivated",
            "complex_create",
            "complex_update",
            "complex_soft_deleted",
            "complex_restored",
            "apartment_create",
            "apartment_update",
            "apartment_delete",
            "billing_create",
            "rebilling",
            "rebilling_request_create",
            "billing_approval",
            "billing_rejection",
            "pdf_create",
            "bulk_pdf_excel_create",
            "meter_retry_started",
            "meter_retry_failed",
            "meter_retry_success",
            "meter_became_faulty",
            "meter_recovered",
            "unexpected_error",
        }

        for code in production_codes:
            self.assertNotEqual(get_action_label(code), UNKNOWN_ACTION_LABEL)
        self.assertEqual(get_action_label("LOGIN_SUCCESS"), "Başarılı Giriş")
