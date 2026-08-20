"""An opening-balance arrears row must survive being paid into.

The cutover row carries the balance brought forward from the old books, not a
month's rent. `_update_arrears` used to recompute `expected_rent` from
`tenant.monthly_rent` on every payment, so the first payment against the cutover
period restated the debt — inflating a small opening arrear to a full month's
rent, or writing off a large one down to the same figure.
"""
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.buildings.models import Building, Unit, UnitStatus
from apps.ledger.posting import post_opening_balances
from apps.payments.models import Arrears
from apps.payments.services import allocate_payment_fifo, process_payment
from apps.tenants.models import Tenant

CUTOVER = "2026-06-16"


class OpeningArrearsTests(TestCase):
    def setUp(self):
        self.building = Building.objects.create(name="Road Block Eldoret", total_floors=4)
        self.unit = Unit.objects.create(
            building=self.building, label="RB305",
            monthly_rent=Decimal("7000"), status=UnitStatus.OCCUPIED_UNPAID,
        )
        self.tenant = Tenant.objects.create(
            first_name="Sheldon", last_name="Mutai", id_number="PENDING-RB305",
            phone="+254707575747", unit=self.unit,
            monthly_rent=Decimal("7000"), move_in_date="2026-01-01",
        )

    def _open(self, amount):
        """Raise a cutover row the way load_property_data does, plus its ledger entry."""
        row = Arrears.objects.create(
            tenant=self.tenant, period_month=6, period_year=2026,
            expected_rent=amount, amount_paid=Decimal("0"),
            balance=amount, is_cleared=amount <= 0,
        )
        post_opening_balances(
            self.tenant, net_balance=amount, deposit=Decimal("0"), date=CUTOVER,
        )
        return row

    def test_payment_does_not_inflate_a_small_opening_balance(self):
        self._open(Decimal("1000"))

        process_payment(
            tenant=self.tenant, amount=Decimal("1000"), payment_date=CUTOVER,
            period_month=6, period_year=2026, source="mpesa",
        )

        row = Arrears.objects.get(tenant=self.tenant, period_month=6, period_year=2026)
        self.assertEqual(row.expected_rent, Decimal("1000.00"))
        self.assertEqual(row.balance, Decimal("0.00"))
        self.assertTrue(row.is_cleared)

    def test_payment_does_not_write_off_a_large_opening_balance(self):
        self._open(Decimal("74700"))

        process_payment(
            tenant=self.tenant, amount=Decimal("9000"), payment_date=CUTOVER,
            period_month=6, period_year=2026, source="mpesa",
        )

        row = Arrears.objects.get(tenant=self.tenant, period_month=6, period_year=2026)
        self.assertEqual(row.expected_rent, Decimal("74700.00"))
        self.assertEqual(row.balance, Decimal("65700.00"))
        self.assertFalse(row.is_cleared)

    def test_fifo_clears_the_opening_row_before_the_month(self):
        """The live regression: 7,000 against a 1,000 opening + a 7,000 month."""
        self._open(Decimal("1000"))
        Arrears.objects.create(
            tenant=self.tenant, period_month=7, period_year=2026,
            expected_rent=Decimal("7000"), amount_paid=Decimal("0"),
            balance=Decimal("7000"), is_cleared=False,
        )

        allocate_payment_fifo(
            tenant=self.tenant, amount=Decimal("7000"), payment_date="2026-08-11",
            source="mpesa", reference="CB0396934_11082026_2",
        )

        june = Arrears.objects.get(tenant=self.tenant, period_month=6)
        july = Arrears.objects.get(tenant=self.tenant, period_month=7)
        self.assertTrue(june.is_cleared)
        self.assertEqual(june.balance, Decimal("0.00"))
        self.assertEqual(july.balance, Decimal("1000.00"))
        # Total owed is the 1,000 still short on July — not the 7,000 the
        # overwrite used to manufacture.
        outstanding = sum(
            a.balance for a in Arrears.objects.filter(tenant=self.tenant, is_cleared=False)
        )
        self.assertEqual(outstanding, Decimal("1000.00"))

    def test_a_period_with_no_row_still_bills_the_month(self):
        """Money for a month no billing run raised falls back to current rent."""
        process_payment(
            tenant=self.tenant, amount=Decimal("2000"), payment_date="2026-09-03",
            period_month=9, period_year=2026, source="mpesa",
        )

        row = Arrears.objects.get(tenant=self.tenant, period_month=9, period_year=2026)
        self.assertEqual(row.expected_rent, Decimal("7000.00"))
        self.assertEqual(row.balance, Decimal("5000.00"))


class RepairCommandTests(TestCase):
    def setUp(self):
        self.building = Building.objects.create(name="Road Block Eldoret", total_floors=4)

    def _damaged(self, label, rent, opening, paid):
        """A tenant whose opening row was already overwritten with monthly rent."""
        unit = Unit.objects.create(
            building=self.building, label=label, monthly_rent=rent,
            status=UnitStatus.OCCUPIED_UNPAID,
        )
        tenant = Tenant.objects.create(
            first_name="T", last_name=label, id_number=f"PENDING-{label}",
            phone="+254700000000", unit=unit, monthly_rent=rent,
            move_in_date="2026-01-01",
        )
        post_opening_balances(
            tenant, net_balance=opening, deposit=Decimal("0"), date=CUTOVER,
        )
        Arrears.objects.create(
            tenant=tenant, period_month=6, period_year=2026,
            expected_rent=rent, amount_paid=paid,
            balance=max(rent - paid, Decimal("0")), is_cleared=paid >= rent,
        )
        return tenant

    def _run(self, *args):
        out = StringIO()
        call_command("repair_opening_arrears", *args, stdout=out)
        return out.getvalue()

    def test_preview_reports_without_writing(self):
        tenant = self._damaged("RB305", Decimal("7000"), Decimal("1000"), Decimal("1000"))

        output = self._run()

        self.assertIn("Preview only", output)
        row = Arrears.objects.get(tenant=tenant)
        self.assertEqual(row.expected_rent, Decimal("7000.00"))  # untouched

    def test_apply_restores_both_directions(self):
        overstated = self._damaged("RB305", Decimal("7000"), Decimal("1000"), Decimal("1000"))
        understated = self._damaged("RB302", Decimal("8300"), Decimal("74700"), Decimal("9000"))

        self._run("--apply")

        small = Arrears.objects.get(tenant=overstated)
        self.assertEqual(small.expected_rent, Decimal("1000.00"))
        self.assertEqual(small.balance, Decimal("0.00"))
        self.assertTrue(small.is_cleared)

        large = Arrears.objects.get(tenant=understated)
        self.assertEqual(large.expected_rent, Decimal("74700.00"))
        self.assertEqual(large.balance, Decimal("65700.00"))
        self.assertFalse(large.is_cleared)

    def test_rerunning_is_a_no_op(self):
        self._damaged("RB305", Decimal("7000"), Decimal("1000"), Decimal("1000"))
        self._run("--apply")

        output = self._run()

        self.assertIn("Nothing to repair", output)

    def test_scopes_to_one_tenant(self):
        keep = self._damaged("RB305", Decimal("7000"), Decimal("1000"), Decimal("1000"))
        other = self._damaged("RB302", Decimal("8300"), Decimal("74700"), Decimal("9000"))

        self._run("--apply", "--tenant", str(keep.pk))

        self.assertEqual(Arrears.objects.get(tenant=keep).expected_rent, Decimal("1000.00"))
        self.assertEqual(Arrears.objects.get(tenant=other).expected_rent, Decimal("8300.00"))

    def test_released_credit_is_swept_onto_open_periods(self):
        """Cutting an inflated opening balance back turns paid cash into credit,
        which must reach the tenant's open months rather than sit banked."""
        tenant = self._damaged("RB410", Decimal("8300"), Decimal("300"), Decimal("8300"))
        july = Arrears.objects.create(
            tenant=tenant, period_month=7, period_year=2026,
            expected_rent=Decimal("8300"), amount_paid=Decimal("0"),
            balance=Decimal("8300"), is_cleared=False,
        )

        output = self._run()
        self.assertIn("release", output)

        self._run("--apply")

        june = Arrears.objects.get(tenant=tenant, period_month=6)
        july.refresh_from_db()
        self.assertEqual(june.expected_rent, Decimal("300.00"))
        # 8,300 paid against a 300 opening leaves 8,000 for July.
        self.assertEqual(july.credit_applied, Decimal("8000.00"))
        self.assertEqual(july.balance, Decimal("300.00"))

    def test_credit_sweep_does_not_double_apply(self):
        tenant = self._damaged("RB410", Decimal("8300"), Decimal("300"), Decimal("8300"))
        Arrears.objects.create(
            tenant=tenant, period_month=7, period_year=2026,
            expected_rent=Decimal("8300"), amount_paid=Decimal("0"),
            balance=Decimal("8300"), is_cleared=False,
        )

        self._run("--apply")
        self._run("--apply")

        july = Arrears.objects.get(tenant=tenant, period_month=7)
        self.assertEqual(july.credit_applied, Decimal("8000.00"))
