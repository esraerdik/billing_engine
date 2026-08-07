"""
tests.py
--------
`BillingCalculator` için birim testleri.

`unittest` standart kütüphanesi kullanılmıştır (harici bağımlılık
gerekmez). Çalıştırmak için proje kök dizininden:

    python -m unittest domain.tests -v
"""

from __future__ import annotations

import unittest
from datetime import datetime

from .authorization import (
    AdminBillingPanel,
    BillingRunAuthorizer,
    UserBillingPanel,
)
from .calculator import BillingCalculator
from .exceptions import (
    AdminApprovalRequiredError,
    BillingEngineError,
    EmptyApartmentListError,
    InvalidBillingPeriodError,
    NegativeAreaError,
    NegativeBillError,
    NegativeEnergyError,
    ZeroAreaError,
    ZeroTotalEnergyError,
)
from .history import BillingHistory
from .models import Apartment, BillingPeriod


class BillingCalculatorHappyPathTests(unittest.TestCase):
    """Geçerli girdilerle doğru hesaplama yapıldığını doğrulayan testler."""

    def setUp(self) -> None:
        self.calculator = BillingCalculator()
        self.apartments = [
            Apartment(id=1, area=120, energy=1250),
            Apartment(id=2, area=95, energy=980),
            Apartment(id=3, area=140, energy=1540),
            Apartment(id=4, area=110, energy=1120),
        ]
        self.total_bill = 45000.0

    def test_fixed_and_consumption_pools_are_70_30_split(self) -> None:
        summary = self.calculator.calculate(self.total_bill, self.apartments)
        self.assertAlmostEqual(summary.total_consumption_amount, 45000.0 * 0.70)
        self.assertAlmostEqual(summary.total_fixed_amount, 45000.0 * 0.30)

    def test_sum_of_apartment_payables_equals_total_bill(self) -> None:
        summary = self.calculator.calculate(self.total_bill, self.apartments)
        self.assertAlmostEqual(
            summary.sum_of_payables(), self.total_bill, places=6
        )

    def test_area_and_energy_ratios_sum_to_one(self) -> None:
        summary = self.calculator.calculate(self.total_bill, self.apartments)
        self.assertAlmostEqual(
            sum(result.area_ratio for result in summary.results), 1.0, places=9
        )
        self.assertAlmostEqual(
            sum(result.energy_ratio for result in summary.results), 1.0, places=9
        )

    def test_single_apartment_pays_entire_bill(self) -> None:
        solo_apartment = [Apartment(id=1, area=100, energy=500)]
        summary = self.calculator.calculate(self.total_bill, solo_apartment)
        self.assertEqual(len(summary.results), 1)
        self.assertAlmostEqual(
            summary.results[0].total_payable, self.total_bill, places=6
        )

    def test_zero_total_bill_produces_zero_shares(self) -> None:
        summary = self.calculator.calculate(0.0, self.apartments)
        for result in summary.results:
            self.assertAlmostEqual(result.total_payable, 0.0)

    def test_known_apartment_result_matches_manual_calculation(self) -> None:
        # Daire 1 için elle hesap: area_ratio = 120/465, energy_ratio = 1250/4890
        summary = self.calculator.calculate(self.total_bill, self.apartments)
        apt1 = next(r for r in summary.results if r.apartment_id == 1)

        total_area = 120 + 95 + 140 + 110
        total_energy = 1250 + 980 + 1540 + 1120
        expected_area_ratio = 120 / total_area
        expected_energy_ratio = 1250 / total_energy
        expected_fixed = (45000.0 * 0.30) * expected_area_ratio
        expected_consumption = (45000.0 * 0.70) * expected_energy_ratio

        self.assertAlmostEqual(apt1.area_ratio, expected_area_ratio, places=9)
        self.assertAlmostEqual(apt1.energy_ratio, expected_energy_ratio, places=9)
        self.assertAlmostEqual(apt1.fixed_share, expected_fixed, places=6)
        self.assertAlmostEqual(apt1.consumption_share, expected_consumption, places=6)
        self.assertAlmostEqual(
            apt1.total_payable, expected_fixed + expected_consumption, places=6
        )


class BillingCalculatorValidationTests(unittest.TestCase):
    """Geçersiz girdilerde doğru özel exception'ların fırlatıldığını doğrular."""

    def setUp(self) -> None:
        self.calculator = BillingCalculator()
        self.valid_apartments = [
            Apartment(id=1, area=100, energy=500),
            Apartment(id=2, area=100, energy=500),
        ]

    def test_negative_bill_raises(self) -> None:
        with self.assertRaises(NegativeBillError):
            self.calculator.calculate(-100.0, self.valid_apartments)

    def test_empty_apartment_list_raises(self) -> None:
        with self.assertRaises(EmptyApartmentListError):
            self.calculator.calculate(1000.0, [])

    def test_negative_area_raises(self) -> None:
        apartments = [Apartment(id=1, area=-50, energy=500)]
        with self.assertRaises(NegativeAreaError):
            self.calculator.calculate(1000.0, apartments)

    def test_negative_energy_raises(self) -> None:
        apartments = [Apartment(id=1, area=50, energy=-500)]
        with self.assertRaises(NegativeEnergyError):
            self.calculator.calculate(1000.0, apartments)

    def test_zero_area_raises(self) -> None:
        apartments = [Apartment(id=1, area=0, energy=500)]
        with self.assertRaises(ZeroAreaError):
            self.calculator.calculate(1000.0, apartments)

    def test_zero_area_raises_even_if_other_apartments_are_valid(self) -> None:
        apartments = [
            Apartment(id=1, area=100, energy=500),
            Apartment(id=2, area=0, energy=500),  # alanı unutulmuş
        ]
        with self.assertRaises(ZeroAreaError) as ctx:
            self.calculator.calculate(1000.0, apartments)
        self.assertIn("2", str(ctx.exception))

    def test_zero_energy_does_not_raise_but_zero_area_does(self) -> None:
        apartments = [
            Apartment(id=1, area=100, energy=0),
            Apartment(id=2, area=100, energy=500),
        ]
        self.calculator.calculate(1000.0, apartments)

        apartments_with_zero_area = [Apartment(id=1, area=0, energy=100)]
        with self.assertRaises(ZeroAreaError):
            self.calculator.calculate(1000.0, apartments_with_zero_area)

    def test_error_messages_contain_apartment_id_context(self) -> None:
        apartments = [Apartment(id=7, area=-10, energy=100)]
        with self.assertRaises(NegativeAreaError) as ctx:
            self.calculator.calculate(1000.0, apartments)
        self.assertIn("7", str(ctx.exception))


class ZeroEnergyHandlingTests(unittest.TestCase):
    """Enerji tüketiminin sıfır olduğu iki senaryoyu doğrular."""

    def setUp(self) -> None:
        self.calculator = BillingCalculator()

    def test_one_empty_apartment_among_others_still_pays_fixed_share(self) -> None:
        apartments = [
            Apartment(id=1, area=100, energy=0),
            Apartment(id=2, area=100, energy=500),
        ]
        summary = self.calculator.calculate(1000.0, apartments)
        empty_apartment = next(r for r in summary.results if r.apartment_id == 1)

        self.assertAlmostEqual(empty_apartment.consumption_share, 0.0)
        self.assertAlmostEqual(empty_apartment.fixed_share, 150.0, places=6)
        self.assertAlmostEqual(empty_apartment.total_payable, 150.0, places=6)

    def test_all_zero_energy_raises(self) -> None:
        apartments = [
            Apartment(id=1, area=100, energy=0),
            Apartment(id=2, area=100, energy=0),
        ]
        with self.assertRaises(ZeroTotalEnergyError):
            self.calculator.calculate(1000.0, apartments)

    def test_single_apartment_zero_energy_also_raises(self) -> None:
        apartments = [Apartment(id=1, area=100, energy=0)]
        with self.assertRaises(ZeroTotalEnergyError):
            self.calculator.calculate(1000.0, apartments)

    def test_at_least_one_nonzero_energy_prevents_the_error(self) -> None:
        apartments = [
            Apartment(id=1, area=100, energy=0),
            Apartment(id=2, area=100, energy=0),
            Apartment(id=3, area=100, energy=1),
        ]
        summary = self.calculator.calculate(1000.0, apartments)
        self.assertEqual(len(summary.results), 3)


class BillingPeriodTests(unittest.TestCase):
    """`BillingPeriod` değer nesnesinin doğrulama ve biçimlendirmesini test eder."""

    def test_invalid_month_raises(self) -> None:
        with self.assertRaises(InvalidBillingPeriodError):
            BillingPeriod(year=2026, month=13)

    def test_str_format_pads_month(self) -> None:
        self.assertEqual(str(BillingPeriod(year=2026, month=8)), "2026-08")

    def test_equal_periods_are_equal_and_hashable(self) -> None:
        period_a = BillingPeriod(year=2026, month=8)
        period_b = BillingPeriod(year=2026, month=8)
        self.assertEqual(period_a, period_b)
        self.assertEqual(hash(period_a), hash(period_b))


class BillingRunAuthorizerTests(unittest.TestCase):
    """Aylık ücretsiz hak / admin onayı mantığını doğrulayan testler."""

    def setUp(self) -> None:
        self.authorizer = BillingRunAuthorizer()
        self.period = BillingPeriod(year=2026, month=8)

    def test_first_run_is_authorized_without_approval(self) -> None:
        self.authorizer.authorize_run(self.period)

    def test_second_run_without_approval_raises(self) -> None:
        self.authorizer.authorize_run(self.period)
        self.authorizer.record_run(self.period)
        with self.assertRaises(AdminApprovalRequiredError):
            self.authorizer.authorize_run(self.period)

    def test_second_run_after_approval_is_authorized(self) -> None:
        self.authorizer.authorize_run(self.period)
        self.authorizer.record_run(self.period)
        self.authorizer.approve(self.period)
        self.authorizer.authorize_run(self.period)

    def test_approval_is_single_use(self) -> None:
        self.authorizer.authorize_run(self.period)
        self.authorizer.record_run(self.period)
        self.authorizer.approve(self.period)
        self.authorizer.authorize_run(self.period)
        self.authorizer.record_run(self.period)
        with self.assertRaises(AdminApprovalRequiredError):
            self.authorizer.authorize_run(self.period)

    def test_different_periods_are_independent(self) -> None:
        other_period = BillingPeriod(year=2026, month=9)
        self.authorizer.authorize_run(self.period)
        self.authorizer.record_run(self.period)
        self.authorizer.authorize_run(other_period)

    def test_failed_calculation_does_not_consume_free_run(self) -> None:
        self.authorizer.authorize_run(self.period)
        self.authorizer.authorize_run(self.period)

    def test_pending_periods_lists_blocked_period(self) -> None:
        self.authorizer.authorize_run(self.period)
        self.authorizer.record_run(self.period)
        with self.assertRaises(AdminApprovalRequiredError):
            self.authorizer.authorize_run(self.period)
        self.assertIn(self.period, self.authorizer.pending_periods())

    def test_deny_clears_pending_without_granting_access(self) -> None:
        self.authorizer.authorize_run(self.period)
        self.authorizer.record_run(self.period)
        with self.assertRaises(AdminApprovalRequiredError):
            self.authorizer.authorize_run(self.period)
        self.authorizer.deny(self.period)
        self.assertNotIn(self.period, self.authorizer.pending_periods())
        with self.assertRaises(AdminApprovalRequiredError):
            self.authorizer.authorize_run(self.period)


class UserAndAdminPanelTests(unittest.TestCase):
    """`UserBillingPanel` ve `AdminBillingPanel`in birlikte doğru çalıştığını doğrular."""

    def setUp(self) -> None:
        self.authorizer = BillingRunAuthorizer()
        self.history = BillingHistory()
        self.user_panel = UserBillingPanel(
            calculator=BillingCalculator(),
            authorizer=self.authorizer,
            history=self.history,
        )
        self.admin_panel = AdminBillingPanel(
            authorizer=self.authorizer, history=self.history
        )
        self.period = BillingPeriod(year=2026, month=8)
        self.apartments = [
            Apartment(id=1, area=100, energy=500),
            Apartment(id=2, area=100, energy=500),
        ]

    def test_first_run_succeeds(self) -> None:
        summary = self.user_panel.run_billing(self.period, 1000.0, self.apartments)
        self.assertAlmostEqual(summary.total_bill, 1000.0)

    def test_second_run_blocked_then_admin_approves(self) -> None:
        self.user_panel.run_billing(self.period, 1000.0, self.apartments)

        with self.assertRaises(AdminApprovalRequiredError):
            self.user_panel.run_billing(self.period, 1000.0, self.apartments)
        self.assertIn(self.period, self.admin_panel.pending_periods())

        self.admin_panel.approve(self.period)
        summary = self.user_panel.run_billing(self.period, 1000.0, self.apartments)
        self.assertAlmostEqual(summary.total_bill, 1000.0)

    def test_third_run_needs_its_own_new_approval(self) -> None:
        self.user_panel.run_billing(self.period, 1000.0, self.apartments)
        self.admin_panel.approve(self.period)
        self.user_panel.run_billing(self.period, 1000.0, self.apartments)

        with self.assertRaises(AdminApprovalRequiredError):
            self.user_panel.run_billing(self.period, 1000.0, self.apartments)

    def test_calculation_error_does_not_consume_free_run(self) -> None:
        with self.assertRaises(BillingEngineError):
            self.user_panel.run_billing(self.period, -100.0, self.apartments)
        summary = self.user_panel.run_billing(self.period, 1000.0, self.apartments)
        self.assertAlmostEqual(summary.total_bill, 1000.0)

    def test_successful_run_is_recorded_in_history(self) -> None:
        summary = self.user_panel.run_billing(self.period, 1000.0, self.apartments)
        latest = self.history.latest_for(self.period)
        self.assertIsNotNone(latest)
        self.assertEqual(latest.summary, summary)
        self.assertIsInstance(latest.recorded_at, datetime)

    def test_failed_run_is_not_recorded_in_history(self) -> None:
        with self.assertRaises(BillingEngineError):
            self.user_panel.run_billing(self.period, -100.0, self.apartments)
        self.assertIsNone(self.history.latest_for(self.period))

    def test_admin_panel_reads_same_history_as_user_panel(self) -> None:
        self.user_panel.run_billing(self.period, 1000.0, self.apartments)
        self.assertEqual(len(self.admin_panel.history_for(self.period)), 1)

    def test_second_run_after_approval_adds_second_history_entry(self) -> None:
        self.user_panel.run_billing(self.period, 1000.0, self.apartments)
        self.admin_panel.approve(self.period)
        self.user_panel.run_billing(self.period, 2000.0, self.apartments)

        entries = self.user_panel.history_for(self.period)
        self.assertEqual(len(entries), 2)
        self.assertAlmostEqual(entries[0].summary.total_bill, 1000.0)
        self.assertAlmostEqual(entries[1].summary.total_bill, 2000.0)


class BillingHistoryTests(unittest.TestCase):
    """`BillingHistory`'nin kayıt/sorgu davranışını doğrulayan testler."""

    def setUp(self) -> None:
        self.history = BillingHistory()
        self.period = BillingPeriod(year=2026, month=8)
        self.summary = BillingCalculator().calculate(
            1000.0, [Apartment(id=1, area=100, energy=500)]
        )

    def test_no_record_returns_none_and_empty_list(self) -> None:
        self.assertIsNone(self.history.latest_for(self.period))
        self.assertEqual(self.history.all_for(self.period), [])

    def test_record_appears_in_latest_and_all(self) -> None:
        entry = self.history.record(self.period, self.summary)
        self.assertEqual(self.history.latest_for(self.period), entry)
        self.assertEqual(self.history.all_for(self.period), [entry])

    def test_multiple_records_for_same_period_are_all_kept(self) -> None:
        first = self.history.record(self.period, self.summary)
        second = self.history.record(self.period, self.summary)
        self.assertEqual(self.history.all_for(self.period), [first, second])
        self.assertEqual(self.history.latest_for(self.period), second)

    def test_periods_on_record_sorted_chronologically(self) -> None:
        later_period = BillingPeriod(year=2026, month=9)
        self.history.record(later_period, self.summary)
        self.history.record(self.period, self.summary)
        self.assertEqual(
            self.history.periods_on_record(), [self.period, later_period]
        )

    def test_all_entries_flattens_across_periods_in_period_order(self) -> None:
        other_period = BillingPeriod(year=2026, month=9)
        entry_aug = self.history.record(self.period, self.summary)
        entry_sep = self.history.record(other_period, self.summary)
        self.assertEqual(self.history.all_entries(), [entry_aug, entry_sep])

    def test_all_for_returns_copy_not_internal_list(self) -> None:
        self.history.record(self.period, self.summary)
        returned = self.history.all_for(self.period)
        returned.append("dışarıdan eklenen sahte kayıt")
        self.assertEqual(len(self.history.all_for(self.period)), 1)


if __name__ == "__main__":
    unittest.main()
