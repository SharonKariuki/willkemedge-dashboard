"""Tests for the RB ground-floor floor-encoding relabel command.

RB01..RB09 -> RB001..RB009, with the old label preserved as a UnitAlias so
payments quoting the old reference keep auto-matching.
"""
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.buildings.models import Building, Unit, UnitAlias
from apps.payments.matching import match_tenant
from apps.tenants.models import Tenant, TenantStatus


class RelabelRbGroundFloorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.rb = Building.objects.create(name="Road Block", code="RB", total_floors=5)
        # Ground floor (two-digit, needs relabelling)
        cls.g01 = Unit.objects.create(building=cls.rb, label="RB01", monthly_rent=Decimal(10000))
        cls.g09 = Unit.objects.create(building=cls.rb, label="RB09", monthly_rent=Decimal(6500))
        # Upper floor (already floor-encoded — must be left untouched)
        cls.f101 = Unit.objects.create(building=cls.rb, label="RB101", monthly_rent=Decimal(9000))

    def _run(self, *args):
        out = StringIO()
        call_command("relabel_rb_ground_floor", *args, stdout=out, stderr=StringIO())
        return out.getvalue()

    def test_dry_run_writes_nothing(self):
        self._run()  # no --apply
        self.g01.refresh_from_db()
        self.assertEqual(self.g01.label, "RB01")
        self.assertFalse(UnitAlias.objects.exists())

    def test_apply_relabels_ground_floor_and_keeps_alias(self):
        self._run("--apply")
        self.g01.refresh_from_db()
        self.g09.refresh_from_db()
        self.assertEqual(self.g01.label, "RB001")
        self.assertEqual(self.g09.label, "RB009")
        # Old labels preserved as aliases pointing back to the same units.
        self.assertEqual(UnitAlias.objects.get(label="RB01").unit, self.g01)
        self.assertEqual(UnitAlias.objects.get(label="RB09").unit, self.g09)

    def test_upper_floor_untouched(self):
        self._run("--apply")
        self.f101.refresh_from_db()
        self.assertEqual(self.f101.label, "RB101")
        self.assertFalse(UnitAlias.objects.filter(label="RB101").exists())

    def test_idempotent(self):
        self._run("--apply")
        self._run("--apply")  # second run is a no-op
        self.assertEqual(Unit.objects.filter(label="RB001").count(), 1)
        self.assertEqual(UnitAlias.objects.filter(label="RB01").count(), 1)

    def test_old_reference_still_matches_after_relabel(self):
        tenant = Tenant.objects.create(
            unit=self.g01, first_name="Demo", last_name="Trader",
            id_number="DEMO-RB01", monthly_rent=Decimal(10000),
            phone="+254700000005", status=TenantStatus.ACTIVE,
            move_in_date="2025-05-01",
        )
        self._run("--apply")
        # A payment that still quotes the OLD label resolves to the tenant.
        self.assertEqual(match_tenant("RB01"), tenant)
        # The new label resolves too.
        self.assertEqual(match_tenant("RB001"), tenant)
