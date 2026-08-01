"""Bill-ref normalisation and FIFO allocation idempotency.

Covers the two failure modes seen in the July 2026 unmatched queue:
  * "90290#RB009" not reaching unit RB09 (harmless zero padding), and
  * one bank credit being bookable twice through two different code paths.
"""
import datetime as dt
from decimal import Decimal

from django.test import TestCase

from apps.buildings.models import Building, Unit, UnitAlias, UnitStatus
from apps.payments.matching import canonical_label, match_tenant
from apps.payments.models import Arrears, Payment
from apps.payments.services import allocate_payment_fifo
from apps.tenants.models import Tenant, TenantStatus


def _tenant(unit, *, first="Ruth", last="Kulundu", idn="T-001", rent="10000"):
    return Tenant.objects.create(
        first_name=first, last_name=last, id_number=idn,
        phone="+254724568501", unit=unit,
        monthly_rent=Decimal(rent), move_in_date="2026-01-01",
        status=TenantStatus.ACTIVE,
    )


class CanonicalLabelTests(TestCase):
    def test_zero_padding_collapses(self):
        assert canonical_label("RB009") == canonical_label("RB09") == "RB|9|"

    def test_hyphen_optional(self):
        assert canonical_label("F03") == canonical_label("F-03") == "F|3|"

    def test_letter_suffix_kept(self):
        assert canonical_label("DON3A") == "DON|3|A"
        assert canonical_label("DON3A") != canonical_label("DON3B")

    def test_distinct_numbers_stay_distinct(self):
        """The padding rule must not merge RB401, RB411 and RB4011."""
        forms = {canonical_label(x) for x in ("RB401", "RB411", "RB4011")}
        assert len(forms) == 3

    def test_unparseable_label_returns_none(self):
        assert canonical_label("SHOP") is None
        assert canonical_label("") is None


class BillRefMatchingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.rb = Building.objects.create(name="Road Block", code="RB", total_floors=5)
        cls.don = Building.objects.create(name="Donholm", code="DON", total_floors=4)
        cls.rb09 = Unit.objects.create(
            building=cls.rb, label="RB09", monthly_rent=Decimal("10000"),
            status=UnitStatus.OCCUPIED_UNPAID,
        )
        cls.don3a = Unit.objects.create(
            building=cls.don, label="DON3A", monthly_rent=Decimal("22000"),
            status=UnitStatus.OCCUPIED_UNPAID,
        )
        cls.ruth = _tenant(cls.rb09)
        cls.zach = _tenant(cls.don3a, first="Zachary", last="Bwonda", idn="T-002", rent="22000")

    def test_exact_label_still_matches(self):
        assert match_tenant("90290#RB09") == self.ruth

    def test_zero_padded_label_matches(self):
        """The real July case: tenant typed RB009 for unit RB09."""
        assert match_tenant("90290#RB009") == self.ruth

    def test_lowercase_matches(self):
        assert match_tenant("90290#rb009") == self.ruth

    def test_bare_house_number_is_not_guessed(self):
        """'3A' could be any building's house 3A — refuse rather than misroute."""
        assert match_tenant("90290#3A") is None

    def test_alias_resolves_bare_house_number(self):
        UnitAlias.objects.create(label="3A", unit=self.don3a, note="Donholm short form")
        assert match_tenant("90290#3A") == self.zach

    def test_alias_also_tolerates_padding(self):
        UnitAlias.objects.create(label="3A", unit=self.don3a)
        assert match_tenant("90290#03A") == self.zach

    def test_ambiguous_padding_refuses_to_guess(self):
        """RB4011 sits between RB401 and RB411 — neither may be assumed."""
        Unit.objects.create(
            building=self.rb, label="RB401", monthly_rent=Decimal("10000"),
            status=UnitStatus.OCCUPIED_UNPAID,
        )
        Unit.objects.create(
            building=self.rb, label="RB411", monthly_rent=Decimal("10000"),
            status=UnitStatus.OCCUPIED_UNPAID,
        )
        assert match_tenant("90290#RB4011") is None

    def test_unknown_ref_still_unmatched(self):
        assert match_tenant("90290#B11") is None

    def test_vacant_unit_yields_no_tenant(self):
        """MR306 case: the unit resolves but has no active tenant to credit."""
        vacant = Unit.objects.create(
            building=self.rb, label="RB77", monthly_rent=Decimal("9000"),
            status=UnitStatus.VACANT,
        )
        assert vacant.label == "RB77"
        assert match_tenant("90290#RB077") is None


class FifoIdempotencyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.building = Building.objects.create(name="Fifo Block", code="FF", total_floors=2)
        cls.unit = Unit.objects.create(
            building=cls.building, label="FF01", monthly_rent=Decimal("9000"),
            status=UnitStatus.OCCUPIED_UNPAID,
        )
        cls.tenant = _tenant(cls.unit, first="Aron", last="Mutai", idn="T-003", rent="9000")

    def setUp(self):
        Payment.objects.filter(tenant=self.tenant).delete()
        Arrears.objects.filter(tenant=self.tenant).delete()

    def _arrear(self, month, year, balance):
        return Arrears.objects.create(
            tenant=self.tenant, period_month=month, period_year=year,
            expected_rent=Decimal("9000"), amount_paid=Decimal("0"),
            balance=Decimal(balance), is_cleared=False,
        )

    def test_replay_does_not_double_book(self):
        self._arrear(6, 2026, "9000")
        kwargs = dict(
            tenant=self.tenant, amount=Decimal("9000"),
            payment_date=dt.date(2026, 7, 27), source="mpesa",
            reference="UGRIK0NEG6", idempotency_key="UGRIK0NEG6",
        )
        first = allocate_payment_fifo(**kwargs)
        second = allocate_payment_fifo(**kwargs)

        assert [p.id for p in first] == [p.id for p in second]
        assert Payment.objects.filter(tenant=self.tenant).count() == len(first)
        assert sum(p.amount for p in Payment.objects.filter(tenant=self.tenant)) == Decimal("9000")

    def test_split_across_periods_is_replay_safe(self):
        self._arrear(5, 2026, "4000")
        self._arrear(6, 2026, "3000")
        kwargs = dict(
            tenant=self.tenant, amount=Decimal("9000"),
            payment_date=dt.date(2026, 7, 27), source="mpesa",
            reference="UGSPLIT1", idempotency_key="UGSPLIT1",
        )
        first = allocate_payment_fifo(**kwargs)
        assert len(first) == 3  # 4000 + 3000 + 2000 spilling into July

        allocate_payment_fifo(**kwargs)
        assert Payment.objects.filter(tenant=self.tenant).count() == 3
        assert sum(p.amount for p in Payment.objects.filter(tenant=self.tenant)) == Decimal("9000")

    def test_two_chunks_in_same_period_both_survive(self):
        """The trap a period-keyed idempotency scheme would spring.

        A partial arrear for the posting month is cleared, then the remainder
        spills into that SAME month — two legitimate rows for 7/2026 sharing one
        reference. Keying on period would silently drop the second.
        """
        self._arrear(7, 2026, "8300")
        payments = allocate_payment_fifo(
            tenant=self.tenant, amount=Decimal("9000"),
            payment_date=dt.date(2026, 7, 27), source="mpesa",
            reference="CB0999356", idempotency_key="CB0999356",
        )
        assert len(payments) == 2
        assert {p.period_month for p in payments} == {7}
        assert sorted(p.amount for p in payments) == [Decimal("700.00"), Decimal("8300.00")]
        assert len({p.idempotency_key for p in payments}) == 2

    def test_blank_key_keeps_legacy_behaviour(self):
        """Manual entry of a genuine second payment must still be possible.

        Both calls share a reference and carry no idempotency key, so neither is
        de-duplicated: the full 10,000 lands. (How it splits across periods is
        FIFO's business — arrears are recomputed from expected_rent after the
        first call — so assert on the money, not the row count.)
        """
        self._arrear(6, 2026, "20000")
        for _ in range(2):
            allocate_payment_fifo(
                tenant=self.tenant, amount=Decimal("5000"),
                payment_date=dt.date(2026, 7, 27), source="cash",
                reference="MANUAL-1",
            )
        booked = Payment.objects.filter(tenant=self.tenant)
        assert sum(p.amount for p in booked) == Decimal("10000")
        assert all(p.idempotency_key == "" for p in booked)

    def test_distinct_transactions_are_not_confused_by_prefix(self):
        """A key that is a prefix of another key must not dedupe against it."""
        self._arrear(6, 2026, "20000")
        a = allocate_payment_fifo(
            tenant=self.tenant, amount=Decimal("1000"),
            payment_date=dt.date(2026, 7, 27), source="mpesa",
            reference="UGT3A1", idempotency_key="UGT3A1",
        )
        b = allocate_payment_fifo(
            tenant=self.tenant, amount=Decimal("2000"),
            payment_date=dt.date(2026, 7, 27), source="mpesa",
            reference="UGT3A18", idempotency_key="UGT3A18",
        )
        assert a[0].id != b[0].id
        assert Payment.objects.filter(tenant=self.tenant).count() == 2
