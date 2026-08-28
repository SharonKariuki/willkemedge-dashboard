"""
The downloaded statement must agree with the rent roll on screen.

Both derive from the same records, but by separate code paths, so they can
drift. Two ways they had: the PDF re-derived VAT at 16% instead of reading what
was raised, and it printed a carried opening balance as though it were a
month's rent.
"""
import datetime as _dt
from decimal import Decimal

import pytest

from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.payments.models import Arrears
from apps.payments.statement_service import build_statement
from apps.tenants.models import Tenant, TenantStatus

D = Decimal
AS_OF = _dt.date(2026, 8, 28)


def _let(label, classification, rent):
    building = Building.objects.create(name=f"B-{label}", code=label[:3], total_floors=1)
    unit = Unit.objects.create(
        building=building, label=label, monthly_rent=D(rent),
        classification=classification, status=UnitStatus.OCCUPIED_UNPAID,
    )
    return Tenant.objects.create(
        first_name="Test", last_name=label, id_number=f"ID-{label}",
        phone="+254700111333", unit=unit, monthly_rent=D(rent),
        move_in_date="2026-07-01", status=TenantStatus.ACTIVE,
    )


def _descriptions(statement):
    return [r["description"] for r in statement["rows"]]


@pytest.mark.django_db
class TestVatIsReadNotDerived:
    def test_a_commercial_letting_billed_without_vat_gets_none(self):
        """MCG02 is commercial and billed 22,500 with no VAT. Deriving 16% here
        charged tax on the statement that the ledger never raised."""
        t = _let("MQA02", UnitClassification.BUSINESS, "22500")
        Arrears.objects.create(
            tenant=t, period_month=8, period_year=2026,
            expected_rent=D("22500"), expected_vat=D("0"),
            amount_paid=D("0"), balance=D("22500"),
        )

        st = build_statement(t, statement_date=AS_OF, as_of=AS_OF)

        assert not any("VAT" in d for d in _descriptions(st)), "VAT charged that was never raised"
        assert st["total_due_value"] == D("22500.00")

    def test_a_vat_rated_letting_still_shows_it(self):
        t = _let("MQA01", UnitClassification.BUSINESS, "24000")
        Arrears.objects.create(
            tenant=t, period_month=8, period_year=2026,
            expected_rent=D("24000"), expected_vat=D("3840"),
            amount_paid=D("0"), balance=D("27840"),
        )

        st = build_statement(t, statement_date=AS_OF, as_of=AS_OF)

        assert any("VAT" in d for d in _descriptions(st))
        assert st["total_due_value"] == D("27840.00")


@pytest.mark.django_db
class TestOpeningBalanceIsNotRent:
    def _with_opening(self, label):
        t = _let(label, UnitClassification.BUSINESS, "22500")
        Arrears.objects.create(
            tenant=t, period_month=7, period_year=2026,
            expected_rent=D("20000"), expected_vat=D("0"),
            amount_paid=D("0"), balance=D("20000"),
            waive_notes="Opening position carried from the 21 Aug 2026 statement.",
        )
        Arrears.objects.create(
            tenant=t, period_month=8, period_year=2026,
            expected_rent=D("22500"), expected_vat=D("3600"),
            amount_paid=D("0"), balance=D("26100"),
        )
        return t

    def test_it_prints_as_brought_forward(self):
        st = build_statement(self._with_opening("MQB03"), statement_date=AS_OF, as_of=AS_OF)

        descriptions = _descriptions(st)
        assert any("Balance brought forward" in d for d in descriptions)
        assert not any(d.startswith("Month Rent - July") for d in descriptions), (
            "a carried balance printed as a month's rent"
        )

    def test_no_vat_is_charged_on_a_carried_balance(self):
        """Whatever tax was due is already inside the figure carried."""
        st = build_statement(self._with_opening("MQB04"), statement_date=AS_OF, as_of=AS_OF)

        vat_rows = [r for r in st["rows"] if "VAT" in r["description"]]
        assert len(vat_rows) == 1, "VAT charged twice, or on the opening balance"

    def test_the_total_matches_the_ledger(self):
        """20,000 carried + 22,500 rent + 3,600 VAT = 46,100 — Elimisha's
        figure on the 21 Aug statement."""
        st = build_statement(self._with_opening("MQB05"), statement_date=AS_OF, as_of=AS_OF)

        assert st["total_due_value"] == D("46100.00")
