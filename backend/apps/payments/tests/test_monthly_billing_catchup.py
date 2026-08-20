"""Billing must catch up months it missed.

There is no Celery beat in production; an external scheduler calls the cron
endpoint. When it does not fire, the task used to look only at `now`, so the
skipped month's rent was never raised — and never would be. Two of those went by
before anyone noticed.
"""
import datetime as dt
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.ledger.posting import post_opening_balances
from apps.payments.models import Arrears
from apps.payments.tasks import generate_monthly_arrears
from apps.tenants.models import Tenant

CUTOVER = dt.date(2026, 6, 16)


def _august():
    """Freeze 'now' at 20 Aug 2026, the day the gap was found."""
    return timezone.make_aware(dt.datetime(2026, 8, 20, 9, 0))


class BillingCatchUpTests(TestCase):
    def setUp(self):
        self.building = Building.objects.create(name="Road Block Eldoret", total_floors=4)
        self._patch_now()

    def _patch_now(self):
        patcher = patch("apps.payments.tasks.timezone.now", return_value=_august())
        patcher.start()
        self.addCleanup(patcher.stop)

    def _tenant(self, label, rent, move_in, *, opening=None, classification=None):
        unit = Unit.objects.create(
            building=self.building, label=label, monthly_rent=Decimal(rent),
            status=UnitStatus.OCCUPIED_UNPAID,
            **({"classification": classification} if classification else {}),
        )
        tenant = Tenant.objects.create(
            first_name="T", last_name=label, id_number=f"PENDING-{label}",
            phone="+254700000000", unit=unit, monthly_rent=Decimal(rent),
            move_in_date=move_in,
        )
        if opening is not None:
            post_opening_balances(
                tenant, net_balance=Decimal(opening), deposit=Decimal("0"), date=CUTOVER,
            )
            Arrears.objects.create(
                tenant=tenant, period_month=6, period_year=2026,
                expected_rent=Decimal(opening), amount_paid=Decimal("0"),
                balance=Decimal(opening), is_cleared=Decimal(opening) <= 0,
            )
        return tenant

    def _periods(self, tenant):
        return sorted(
            Arrears.objects.filter(tenant=tenant).values_list("period_year", "period_month")
        )

    def test_raises_every_missed_month_not_just_the_current_one(self):
        tenant = self._tenant("RB305", "7000", "2026-01-01", opening="1000")

        generate_monthly_arrears()

        # June is the cutover row; July and August are the rent months missed.
        self.assertEqual(self._periods(tenant), [(2026, 6), (2026, 7), (2026, 8)])

    def test_does_not_bill_before_the_cutover(self):
        """The opening balance already covers everything up to changeover."""
        tenant = self._tenant("RB302", "8300", "2024-03-01", opening="74700")

        generate_monthly_arrears()

        self.assertEqual(self._periods(tenant), [(2026, 6), (2026, 7), (2026, 8)])

    def test_does_not_bill_before_move_in(self):
        tenant = self._tenant("RB304", "8300", "2026-08-15")

        generate_monthly_arrears()

        self.assertEqual(self._periods(tenant), [(2026, 8)])

    def test_bills_a_tenant_who_has_never_been_billed(self):
        """Moved in after the last run, so had no rows at all — and was
        invisible to the arrears report and the reminders."""
        self._tenant("RB999", "9000", "2026-06-20", opening="0")  # anchors the cutover
        tenant = self._tenant("RB203", "9000", "2026-07-01")

        generate_monthly_arrears()

        self.assertEqual(self._periods(tenant), [(2026, 7), (2026, 8)])
        self.assertEqual(
            sum(a.balance for a in Arrears.objects.filter(tenant=tenant)),
            Decimal("18000.00"),
        )

    def test_is_idempotent(self):
        tenant = self._tenant("RB305", "7000", "2026-01-01", opening="1000")

        generate_monthly_arrears()
        first = self._periods(tenant)
        generate_monthly_arrears()

        self.assertEqual(self._periods(tenant), first)

    def test_commercial_month_carries_vat(self):
        tenant = self._tenant(
            "MCG05", "86500", "2026-07-01", classification=UnitClassification.BUSINESS,
        )
        self._tenant("RB999", "9000", "2026-06-20", opening="0")  # anchors the cutover

        generate_monthly_arrears()

        july = Arrears.objects.get(tenant=tenant, period_month=7)
        self.assertEqual(july.expected_rent, Decimal("86500.00"))
        self.assertEqual(july.expected_vat, Decimal("13840.00"))
        self.assertEqual(july.balance, Decimal("100340.00"))

    def test_banked_credit_pays_the_oldest_missed_month_first(self):
        tenant = self._tenant("RB410", "8300", "2026-01-01", opening="300")
        # Overpaid the opening balance by 8,000.
        row = Arrears.objects.get(tenant=tenant, period_month=6)
        row.amount_paid = Decimal("8300")
        row.balance = Decimal("0")
        row.is_cleared = True
        row.save()

        generate_monthly_arrears()

        july = Arrears.objects.get(tenant=tenant, period_month=7)
        august = Arrears.objects.get(tenant=tenant, period_month=8)
        self.assertEqual(july.credit_applied, Decimal("8000.00"))
        self.assertEqual(july.balance, Decimal("300.00"))
        self.assertEqual(august.credit_applied, Decimal("0.00"))
        self.assertEqual(august.balance, Decimal("8300.00"))


class BackfillCommandTests(TestCase):
    def setUp(self):
        self.building = Building.objects.create(name="Road Block Eldoret", total_floors=4)
        patcher = patch("apps.payments.tasks.timezone.now", return_value=_august())
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher2 = patch(
            "apps.payments.management.commands.backfill_arrears.timezone.now",
            return_value=_august(),
        )
        patcher2.start()
        self.addCleanup(patcher2.stop)

        unit = Unit.objects.create(
            building=self.building, label="RB305", monthly_rent=Decimal("7000"),
            status=UnitStatus.OCCUPIED_UNPAID,
        )
        self.tenant = Tenant.objects.create(
            first_name="Sheldon", last_name="Mutai", id_number="PENDING-RB305",
            phone="+254707575747", unit=unit, monthly_rent=Decimal("7000"),
            move_in_date="2026-01-01",
        )
        post_opening_balances(
            self.tenant, net_balance=Decimal("1000"), deposit=Decimal("0"), date=CUTOVER,
        )
        Arrears.objects.create(
            tenant=self.tenant, period_month=6, period_year=2026,
            expected_rent=Decimal("1000"), amount_paid=Decimal("0"),
            balance=Decimal("1000"), is_cleared=False,
        )

    def _run(self, *args):
        out = StringIO()
        call_command("backfill_arrears", *args, stdout=out)
        return out.getvalue()

    def test_preview_writes_nothing(self):
        output = self._run()

        self.assertIn("Preview only", output)
        self.assertIn("14,000.00", output)  # two months at 7,000
        self.assertEqual(Arrears.objects.filter(tenant=self.tenant).count(), 1)

    def test_apply_raises_the_rows(self):
        self._run("--apply")

        self.assertEqual(Arrears.objects.filter(tenant=self.tenant).count(), 3)

    def test_flags_a_tenant_with_no_rent_on_file(self):
        unit = Unit.objects.create(
            building=self.building, label="RB406", monthly_rent=Decimal("0"),
            status=UnitStatus.OCCUPIED_UNPAID,
        )
        Tenant.objects.create(
            first_name="Stephen", last_name="Oyugi", id_number="PENDING-RB406",
            phone="+254727413773", unit=unit, monthly_rent=Decimal("0"),
            move_in_date="2026-01-01",
        )

        output = self._run()

        self.assertIn("no rent on file", output)
        self.assertIn("RB406", output)
