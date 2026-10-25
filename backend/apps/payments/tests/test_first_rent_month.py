"""A letting is charged from its first rent month, and money paid before it
pays that month.

MR203 got the keys on 31 October and starts paying rent in November. The run
billed October (the move-in month, in full), and the 25,000 he paid on
15 October was booked to October too — the allocator puts money beyond known
arrears on the payment date's month, and booking rent to a month with no row
creates that month at a full rent. Deleting the wrong month did not help: the
catch-up bills every month from move-in onward, so the next run raised it
again (MR308's September).
"""
import datetime as dt
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.buildings.models import Building, Unit, UnitStatus
from apps.payments.models import Arrears, Payment, PaymentType
from apps.payments.serializers import PaymentCreateSerializer
from apps.payments.services import RentBeforeFirstMonth, allocate_payment_fifo, process_payment
from apps.payments.tasks import generate_monthly_arrears
from apps.tenants.models import Tenant
from apps.tenants.serializers import TenantEditSerializer, clean_first_rent_month


def _late_august():
    """29 Aug 2026: past the residential run day, so September is raised."""
    return timezone.make_aware(dt.datetime(2026, 8, 29, 9, 0))


class FirstRentMonthTests(TestCase):
    def setUp(self):
        self.building = Building.objects.create(name="Matasia Residential", total_floors=3)
        patcher = patch("apps.payments.tasks.timezone.now", return_value=_late_august())
        patcher.start()
        self.addCleanup(patcher.stop)

    def _tenant(self, label, move_in, first_rent_month=None, rent="27000"):
        unit = Unit.objects.create(
            building=self.building, label=label, monthly_rent=Decimal(rent),
            status=UnitStatus.OCCUPIED_UNPAID,
        )
        return Tenant.objects.create(
            first_name="T", last_name=label, id_number=f"PENDING-{label}",
            phone="+254700000000", unit=unit, monthly_rent=Decimal(rent),
            move_in_date=move_in, first_rent_month=first_rent_month,
        )

    def _periods(self, tenant):
        return sorted(
            Arrears.objects.filter(tenant=tenant).values_list("period_year", "period_month")
        )

    # --- billing ---------------------------------------------------------

    def test_move_in_month_is_billed_when_no_first_rent_month_is_set(self):
        tenant = self._tenant("MR201", dt.date(2026, 7, 31))

        generate_monthly_arrears()

        self.assertEqual(self._periods(tenant), [(2026, 7), (2026, 8), (2026, 9)])

    def test_billing_starts_at_the_first_rent_month(self):
        tenant = self._tenant("MR203", dt.date(2026, 7, 31), dt.date(2026, 8, 1))

        generate_monthly_arrears()

        self.assertEqual(self._periods(tenant), [(2026, 8), (2026, 9)])

    def test_catch_up_never_brings_back_a_month_before_the_first_rent_month(self):
        tenant = self._tenant("MR308", dt.date(2026, 7, 28), dt.date(2026, 8, 1))

        generate_monthly_arrears()
        generate_monthly_arrears()

        self.assertNotIn((2026, 7), self._periods(tenant))

    # --- money paid before the first rent month --------------------------

    def test_money_paid_before_the_first_rent_month_pays_that_month(self):
        tenant = self._tenant("MR203", dt.date(2026, 7, 31), dt.date(2026, 8, 1))

        [payment] = allocate_payment_fifo(
            tenant=tenant, amount=Decimal("27000"), payment_date=dt.date(2026, 7, 15),
            source="mpesa", reference="CB0403388", idempotency_key="CB0403388",
        )

        self.assertEqual((payment.period_year, payment.period_month), (2026, 8))
        self.assertEqual(self._periods(tenant), [(2026, 8)])
        self.assertTrue(Arrears.objects.get(tenant=tenant, period_month=8).is_cleared)

    def test_money_paid_before_move_in_pays_the_move_in_month(self):
        """DON2A: moves in 1 November, paid on 25 October."""
        tenant = self._tenant("DON2A", dt.date(2026, 8, 1), rent="20000")

        [payment] = allocate_payment_fifo(
            tenant=tenant, amount=Decimal("20000"), payment_date=dt.date(2026, 7, 25),
            source="mpesa", reference="CB0795825",
        )

        self.assertEqual((payment.period_year, payment.period_month), (2026, 8))
        self.assertEqual(self._periods(tenant), [(2026, 8)])

    def test_the_next_run_finds_the_prepaid_month_already_paid(self):
        tenant = self._tenant("MR203", dt.date(2026, 7, 31), dt.date(2026, 8, 1))
        allocate_payment_fifo(
            tenant=tenant, amount=Decimal("27000"), payment_date=dt.date(2026, 7, 15),
            source="mpesa", reference="CB0403388",
        )

        generate_monthly_arrears()

        august = Arrears.objects.get(tenant=tenant, period_year=2026, period_month=8)
        self.assertEqual(august.balance, Decimal("0"))
        self.assertEqual(self._periods(tenant), [(2026, 8), (2026, 9)])

    def test_rent_cannot_be_booked_to_a_month_before_the_first_rent_month(self):
        tenant = self._tenant("MR203", dt.date(2026, 7, 31), dt.date(2026, 8, 1))

        with self.assertRaises(RentBeforeFirstMonth):
            process_payment(
                tenant=tenant, amount=Decimal("27000"), payment_date=dt.date(2026, 7, 15),
                period_month=7, period_year=2026, source="cash",
            )
        self.assertFalse(Payment.objects.filter(tenant=tenant).exists())
        self.assertEqual(self._periods(tenant), [])

    def test_a_deposit_can_still_be_received_before_the_first_rent_month(self):
        tenant = self._tenant("MR203", dt.date(2026, 7, 31), dt.date(2026, 8, 1))

        process_payment(
            tenant=tenant, amount=Decimal("28000"), payment_date=dt.date(2026, 7, 15),
            period_month=7, period_year=2026, source="mpesa",
            payment_type=PaymentType.DEPOSIT,
        )

        self.assertEqual(self._periods(tenant), [])

    # --- record payment screen -------------------------------------------

    def _payment_form(self, tenant, **overrides):
        data = {
            "tenant": tenant.pk, "amount": "27000", "payment_date": "2026-07-15",
            "period_month": 7, "period_year": 2026, "source": "cash",
            "payment_type": "rent",
        }
        data.update(overrides)
        return PaymentCreateSerializer(data=data)

    def test_record_payment_refuses_rent_before_the_first_rent_month(self):
        tenant = self._tenant("MR203", dt.date(2026, 7, 31), dt.date(2026, 8, 1))

        form = self._payment_form(tenant)

        self.assertFalse(form.is_valid())
        self.assertIn("rent starts 8/2026", str(form.errors["period_month"]))

    def test_record_payment_accepts_a_deposit_before_the_first_rent_month(self):
        tenant = self._tenant("MR203", dt.date(2026, 7, 31), dt.date(2026, 8, 1))

        self.assertTrue(self._payment_form(tenant, payment_type="deposit").is_valid())

    def test_record_payment_can_still_pay_a_month_already_on_the_books(self):
        """A legacy row before the first rent month stays payable."""
        tenant = self._tenant("RB109", dt.date(2026, 8, 1))
        Arrears.objects.create(
            tenant=tenant, period_month=7, period_year=2026, expected_rent=Decimal("5000"),
            amount_paid=Decimal("0"), balance=Decimal("5000"),
        )

        self.assertTrue(self._payment_form(tenant, amount="5000").is_valid())

    # --- the tenant card -------------------------------------------------

    def test_first_rent_month_is_stored_as_the_first_of_the_month(self):
        self.assertEqual(
            clean_first_rent_month(dt.date(2026, 11, 17), dt.date(2026, 10, 31)),
            dt.date(2026, 11, 1),
        )

    def test_first_rent_month_cannot_be_before_move_in(self):
        with self.assertRaises(ValidationError):
            clean_first_rent_month(dt.date(2026, 9, 1), dt.date(2026, 10, 31))

    def test_first_rent_month_cannot_be_far_after_move_in(self):
        with self.assertRaises(ValidationError):
            clean_first_rent_month(dt.date(2027, 1, 1), dt.date(2026, 10, 31))

    def test_edit_cannot_move_the_first_rent_month_past_a_charged_month(self):
        tenant = self._tenant("MR308", dt.date(2026, 7, 28))
        generate_monthly_arrears()

        form = TenantEditSerializer(tenant, data={"first_rent_month": "2026-08-01"}, partial=True)

        self.assertFalse(form.is_valid())
        self.assertIn("7/2026 is already charged", str(form.errors["first_rent_month"]))

    def test_edit_sets_the_first_rent_month_before_anything_is_charged(self):
        tenant = self._tenant("MR203", dt.date(2026, 7, 31))

        form = TenantEditSerializer(tenant, data={"first_rent_month": "2026-08-01"}, partial=True)

        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        generate_monthly_arrears()
        self.assertEqual(self._periods(tenant), [(2026, 8), (2026, 9)])

    def test_edit_resaving_an_unchanged_first_rent_month_is_fine(self):
        tenant = self._tenant("MR203", dt.date(2026, 7, 31), dt.date(2026, 8, 1))
        generate_monthly_arrears()

        form = TenantEditSerializer(tenant, data={"first_rent_month": "2026-08-01"}, partial=True)

        self.assertTrue(form.is_valid(), form.errors)
