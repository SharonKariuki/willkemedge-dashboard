"""The Statement Summary must add up, and every line must mean something.

The summary had no line for money received, so "Arrears / Others" — derived as
`total_due - rent - VAT` — quietly absorbed whatever the tenant had paid and
swung negative the moment they settled the month. Sidai Healthcare (MCF12) read
"Arrears / Others  -48,760" beside a current month of 50,655 that had in fact
been paid in full, implying a credit the tenant did not have.
"""
import datetime as _dt
from decimal import Decimal

import pytest

from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.payments.models import Arrears, Payment, PaymentSource, PaymentType
from apps.payments.statement_service import build_statement
from apps.tenants.models import Tenant

STATEMENT_DATE = _dt.date(2026, 8, 28)


def _money(text: str) -> Decimal:
    """Parse a formatted statement figure back to a Decimal."""
    return Decimal(text.replace(",", ""))


def _foots(statement) -> None:
    """Arrears + rent + VAT - payments must equal the total due."""
    total = (
        _money(statement["arrears_others"])
        + _money(statement["current_month_rent"])
        + _money(statement["vat_on_rent"])
        - _money(statement["payments_received"])
    )
    assert total == _money(statement["total_due"])


@pytest.fixture
def commercial_unit(db):
    building = Building.objects.create(
        name="Wilkem Edge Business Arcade - Matasia Commercial", total_floors=2
    )
    return Unit.objects.create(
        building=building, label="MCF12", monthly_rent=Decimal("50655"),
        classification=UnitClassification.BUSINESS, status=UnitStatus.OCCUPIED_UNPAID,
    )


@pytest.fixture
def sidai(commercial_unit):
    """Sidai Healthcare on MCF12 — July charge unpaid, August settled in full."""
    tenant = Tenant.objects.create(
        first_name="Sidai", last_name="Healthcare", id_number="PENDING-MCF12",
        phone="+254722301981", unit=commercial_unit,
        monthly_rent=Decimal("50655"), move_in_date="2026-07-21",
    )
    Arrears.objects.create(
        tenant=tenant, period_month=7, period_year=2026,
        expected_rent=Decimal("10000"), expected_vat=Decimal("0"),
        amount_paid=Decimal("0"), balance=Decimal("10000"), is_cleared=False,
    )
    Arrears.objects.create(
        tenant=tenant, period_month=8, period_year=2026,
        expected_rent=Decimal("50655"), expected_vat=Decimal("8105"),
        amount_paid=Decimal("58760"), balance=Decimal("0"), is_cleared=True,
    )
    Payment.objects.create(
        tenant=tenant, amount=Decimal("58760"), payment_date=_dt.date(2026, 8, 21),
        period_month=8, period_year=2026, source=PaymentSource.BANK,
        payment_type=PaymentType.RENT, reference="STMT-2026-08-MCF12",
    )
    return tenant


@pytest.mark.django_db
class TestSidaiStatement:
    def test_arrears_line_is_the_real_july_charge_not_a_negative_plug(self, sidai):
        s = build_statement(sidai, statement_date=STATEMENT_DATE)

        # Was "-48,760.00" — the August payment netted invisibly into arrears.
        assert s["arrears_others"] == "10,000.00"

    def test_payment_is_shown_on_its_own_line(self, sidai):
        s = build_statement(sidai, statement_date=STATEMENT_DATE)

        assert s["payments_received"] == "58,760.00"
        assert s["payments_received_value"] == Decimal("58760.00")

    def test_total_due_is_unchanged_and_the_column_foots(self, sidai):
        s = build_statement(sidai, statement_date=STATEMENT_DATE)

        assert s["total_due"] == "10,000.00"
        assert s["current_month_rent"] == "50,655.00"
        assert s["vat_on_rent"] == "8,105.00"
        _foots(s)


@pytest.mark.django_db
class TestSummaryFootsInEveryShape:
    def _tenant(self, unit, label, rent):
        return Tenant.objects.create(
            first_name="T", last_name=label, id_number=f"PENDING-{label}",
            phone="+254700000000", unit=unit, monthly_rent=Decimal(rent),
            move_in_date="2026-07-01",
        )

    def test_nothing_paid_this_month_reads_exactly_as_before(self, commercial_unit):
        """The old formula was right in this one case; it must stay right."""
        tenant = self._tenant(commercial_unit, "MCF13", "50655")
        Arrears.objects.create(
            tenant=tenant, period_month=7, period_year=2026,
            expected_rent=Decimal("10000"), expected_vat=Decimal("0"),
            amount_paid=Decimal("0"), balance=Decimal("10000"), is_cleared=False,
        )
        Arrears.objects.create(
            tenant=tenant, period_month=8, period_year=2026,
            expected_rent=Decimal("50655"), expected_vat=Decimal("8105"),
            amount_paid=Decimal("0"), balance=Decimal("58760"), is_cleared=False,
        )

        s = build_statement(tenant, statement_date=STATEMENT_DATE)

        assert s["arrears_others"] == "10,000.00"
        assert s["payments_received"] == "0.00"
        # Falsy, so the template hides the row and the layout is untouched.
        assert not s["payments_received_value"]
        assert s["total_due"] == "68,760.00"
        _foots(s)

    def test_part_paid_month(self, commercial_unit):
        tenant = self._tenant(commercial_unit, "MCF14", "50655")
        Arrears.objects.create(
            tenant=tenant, period_month=7, period_year=2026,
            expected_rent=Decimal("10000"), expected_vat=Decimal("0"),
            amount_paid=Decimal("0"), balance=Decimal("10000"), is_cleared=False,
        )
        Arrears.objects.create(
            tenant=tenant, period_month=8, period_year=2026,
            expected_rent=Decimal("50655"), expected_vat=Decimal("8105"),
            amount_paid=Decimal("20000"), balance=Decimal("38760"), is_cleared=False,
        )
        Payment.objects.create(
            tenant=tenant, amount=Decimal("20000"), payment_date=_dt.date(2026, 8, 10),
            period_month=8, period_year=2026, source=PaymentSource.MPESA,
        )

        s = build_statement(tenant, statement_date=STATEMENT_DATE)

        assert s["arrears_others"] == "10,000.00"
        assert s["payments_received"] == "20,000.00"
        assert s["total_due"] == "48,760.00"
        _foots(s)

    def test_overpaid_month_shows_a_credit_not_a_broken_arrears_line(self, commercial_unit):
        """Sidai Lonestar on MCG05: 102,600 received against 100,340 due."""
        unit = Unit.objects.create(
            building=commercial_unit.building, label="MCG05",
            monthly_rent=Decimal("86500"), classification=UnitClassification.BUSINESS,
            status=UnitStatus.OCCUPIED_UNPAID,
        )
        tenant = self._tenant(unit, "MCG05", "86500")
        Arrears.objects.create(
            tenant=tenant, period_month=8, period_year=2026,
            expected_rent=Decimal("86500"), expected_vat=Decimal("13840"),
            amount_paid=Decimal("102600"), balance=Decimal("0"), is_cleared=True,
        )
        Payment.objects.create(
            tenant=tenant, amount=Decimal("102600"), payment_date=_dt.date(2026, 8, 14),
            period_month=8, period_year=2026, source=PaymentSource.BANK,
            reference="CB0327111_14082026_1",
        )

        s = build_statement(tenant, statement_date=STATEMENT_DATE)

        # No earlier period, so nothing is brought forward — this was -100,340.
        assert s["arrears_others"] == "0.00"
        assert s["payments_received"] == "102,600.00"
        assert _money(s["total_due"]) == Decimal("-2260.00")
        _foots(s)

    def test_deposit_is_not_counted_as_a_rent_payment(self, commercial_unit):
        """A deposit is a refundable liability; the ledger excludes it, so the
        summary must too or the column stops footing."""
        tenant = self._tenant(commercial_unit, "MCF15", "50655")
        Arrears.objects.create(
            tenant=tenant, period_month=8, period_year=2026,
            expected_rent=Decimal("50655"), expected_vat=Decimal("8105"),
            amount_paid=Decimal("0"), balance=Decimal("58760"), is_cleared=False,
        )
        Payment.objects.create(
            tenant=tenant, amount=Decimal("151965"), payment_date=_dt.date(2026, 8, 1),
            period_month=8, period_year=2026, source=PaymentSource.BANK,
            payment_type=PaymentType.DEPOSIT, reference="DEPOSIT-MCF15",
        )

        s = build_statement(tenant, statement_date=STATEMENT_DATE)

        assert s["payments_received"] == "0.00"
        assert s["total_due"] == "58,760.00"
        _foots(s)

    def test_voided_payment_does_not_reach_the_summary(self, commercial_unit):
        from django.utils import timezone

        tenant = self._tenant(commercial_unit, "MCF16", "50655")
        Arrears.objects.create(
            tenant=tenant, period_month=8, period_year=2026,
            expected_rent=Decimal("50655"), expected_vat=Decimal("8105"),
            amount_paid=Decimal("0"), balance=Decimal("58760"), is_cleared=False,
        )
        Payment.objects.create(
            tenant=tenant, amount=Decimal("58760"), payment_date=_dt.date(2026, 8, 5),
            period_month=8, period_year=2026, source=PaymentSource.BANK,
            voided_at=timezone.now(), void_reason="duplicate capture",
        )

        s = build_statement(tenant, statement_date=STATEMENT_DATE)

        assert s["payments_received"] == "0.00"
        assert s["total_due"] == "58,760.00"
        _foots(s)


@pytest.mark.django_db
class TestTemplateRendersTheLine:
    """The row must actually reach the PDF, and disappear when nothing is paid."""

    def _render(self, tenant):
        from django.template.loader import render_to_string
        return render_to_string(
            "payments/statement_pdf.html",
            build_statement(tenant, statement_date=STATEMENT_DATE),
        )

    def test_row_appears_when_the_tenant_has_paid(self, sidai):
        html = self._render(sidai)

        assert "Less: Payments Received" in html
        assert "(58,760.00)" in html

    def test_row_is_absent_when_nothing_has_been_paid(self, commercial_unit):
        tenant = Tenant.objects.create(
            first_name="Unpaid", last_name="Tenant", id_number="PENDING-MCF17",
            phone="+254700000000", unit=commercial_unit,
            monthly_rent=Decimal("50655"), move_in_date="2026-07-01",
        )
        Arrears.objects.create(
            tenant=tenant, period_month=8, period_year=2026,
            expected_rent=Decimal("50655"), expected_vat=Decimal("8105"),
            amount_paid=Decimal("0"), balance=Decimal("58760"), is_cleared=False,
        )

        html = self._render(tenant)

        assert "Less: Payments Received" not in html
