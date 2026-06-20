"""Global unique unit labels + old-label alias fallback for payment matching.

These guard the building-code relabel: every unit label is unique across the
whole portfolio (so a payment reference maps to exactly one unit), and a unit's
retired labels keep matching during the transition via UnitAlias.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.buildings.models import Building, Unit, UnitAlias, UnitStatus
from apps.payments.matching import match_tenant
from apps.tenants.models import Tenant, TenantStatus


class LabelUniquenessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.don = Building.objects.create(name="Donholm", code="DON", total_floors=4)
        cls.rb = Building.objects.create(name="Road Block", code="RB", total_floors=5)

    def _unit(self, building, label, rent=10000):
        return Unit.objects.create(building=building, label=label, monthly_rent=Decimal(rent))

    def test_same_label_different_buildings_blocked_at_db(self):
        self._unit(self.don, "DON1A")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._unit(self.rb, "DON1A")

    def test_collision_is_case_insensitive(self):
        self._unit(self.don, "DON1A")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._unit(self.rb, "don1a")

    def test_clean_gives_friendly_label_error(self):
        self._unit(self.don, "DON1A")
        dup = Unit(building=self.rb, label="DON1A", monthly_rent=Decimal(10000))
        with self.assertRaises(ValidationError) as ctx:
            dup.full_clean()
        self.assertIn("label", ctx.exception.message_dict)

    def test_distinct_labels_across_buildings_ok(self):
        self._unit(self.don, "DON1A")
        self._unit(self.rb, "RB01")  # different label — fine
        self.assertEqual(Unit.objects.count(), 2)

    def test_label_is_stripped_on_save(self):
        u = self._unit(self.don, "  DON1A  ")
        u.refresh_from_db()
        self.assertEqual(u.label, "DON1A")


class AliasTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.don = Building.objects.create(name="Donholm", code="DON", total_floors=4)
        cls.unit = Unit.objects.create(
            building=cls.don, label="DON1A", monthly_rent=Decimal(10000),
        )

    def test_alias_clashing_with_current_label_rejected(self):
        alias = UnitAlias(unit=self.unit, label="DON1A")
        with self.assertRaises(ValidationError):
            alias.full_clean()

    def test_two_aliases_same_label_blocked_at_db(self):
        UnitAlias.objects.create(unit=self.unit, label="G01")
        other = Unit.objects.create(building=self.don, label="DON1B", monthly_rent=Decimal(10000))
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                UnitAlias.objects.create(unit=other, label="g01")


class MatcherTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.don = Building.objects.create(name="Donholm", code="DON", total_floors=4)
        cls.unit = Unit.objects.create(
            building=cls.don, label="DON1A", monthly_rent=Decimal(10000),
            status=UnitStatus.OCCUPIED_UNPAID,
        )
        cls.tenant = Tenant.objects.create(
            first_name="Jane", last_name="Doe", id_number="999000",
            phone="+254700000000", unit=cls.unit, monthly_rent=Decimal(10000),
            move_in_date="2026-01-01", status=TenantStatus.ACTIVE,
        )

    def test_matches_new_label_with_prefix(self):
        self.assertEqual(match_tenant("90290#DON1A"), self.tenant)

    def test_matches_bare_label(self):
        self.assertEqual(match_tenant("DON1A"), self.tenant)

    def test_falls_back_to_retired_label_alias(self):
        UnitAlias.objects.create(unit=self.unit, label="G01")
        self.assertEqual(match_tenant("90290#G01"), self.tenant)

    def test_unknown_label_returns_none(self):
        self.assertIsNone(match_tenant("90290#ZZZ"))
