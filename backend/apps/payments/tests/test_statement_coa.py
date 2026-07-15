"""
Statement-as-receipt: six lines, each itemised with a COA code (Barclay F8).

Acceptance criteria:
  Security Deposit · Arrears B/F · Month Rent · Other Charges ·
  Rent + Arrears · Unpaid Balance — each carrying its GL code, identical
  across the SMS, the email, and the PDF.
"""
import datetime as _dt
from decimal import Decimal

import pytest

from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.payments.models import (
    Arrears,
    Payment,
    PaymentSource,
    PaymentType,
    UtilityCharge,
)
from apps.payments.statement_service import build_statement
from apps.tenants.models import Tenant, TenantStatus

AS_OF = _dt.date(2026, 4, 13)

EXPECTED_LINES = [
    "Security Deposit",
    "Arrears Brought Forward",
    "Month Rent",
    "Other Charges",
    "Rent + Arrears",
    "Unpaid Balance",
]


def _make_tenant(classification, label):
    building = Building.objects.create(name=f"B{label}", code=label[:3], total_floors=1)
    unit = Unit.objects.create(
        building=building, label=label, monthly_rent=Decimal("12000"),
        classification=classification, status=UnitStatus.OCCUPIED_UNPAID,
    )
    t = Tenant.objects.create(
        first_name="Pat", last_name=label, id_number=f"ID{label}",
        phone="+254700111222", email="pat@example.com", unit=unit,
        monthly_rent=Decimal("12000"), move_in_date="2026-01-01",
        status=TenantStatus.ACTIVE,
    )
    Arrears.objects.create(
        tenant=t, period_month=3, period_year=2026,
        expected_rent=Decimal("12000"), amount_paid=Decimal("4000"),
        balance=Decimal("8000"), is_cleared=False,
    )
    Arrears.objects.create(
        tenant=t, period_month=4, period_year=2026,
        expected_rent=Decimal("12000"), amount_paid=Decimal("0"),
        balance=Decimal("12000"), is_cleared=False,
    )
    Payment.objects.create(
        tenant=t, amount=Decimal("12000"), payment_date="2026-01-01",
        period_month=1, period_year=2026, source=PaymentSource.MPESA,
        payment_type=PaymentType.DEPOSIT, reference="DEP",
    )
    UtilityCharge.objects.create(
        tenant=t, posting_date="2026-04-05", period_month=4, period_year=2026,
        label="Water Usage", amount=Decimal("1500"),
    )
    return t


@pytest.fixture
def residential(db):
    return _make_tenant(UnitClassification.RESIDENTIAL, "DON1A")


@pytest.fixture
def commercial(db):
    return _make_tenant(UnitClassification.BUSINESS, "MCG01")


@pytest.mark.django_db
class TestBreakdownLines:
    def test_all_six_lines_present_in_order(self, residential):
        st = build_statement(residential, statement_date=AS_OF, as_of=AS_OF)
        assert [line[0] for line in st["breakdown_lines"]] == EXPECTED_LINES

    def test_every_line_carries_a_coa_code(self, residential):
        st = build_statement(residential, statement_date=AS_OF, as_of=AS_OF)
        for label, _amount, code, name in st["breakdown_lines"]:
            assert code, f"{label} has no COA code"
            assert code.isdigit(), f"{label} code {code!r} is not a GL code"
            assert name

    def test_codes_map_to_the_chart(self, residential):
        st = build_statement(residential, statement_date=AS_OF, as_of=AS_OF)
        codes = {label: code for label, _a, code, _n in st["breakdown_lines"]}
        assert codes["Security Deposit"] == "2100"         # deposits held (liability)
        assert codes["Arrears Brought Forward"] == "1040"  # receivable
        assert codes["Other Charges"] == "4150"            # utilities recovered
        assert codes["Unpaid Balance"] == "1040"

    def test_rent_line_uses_residential_income_code(self, residential):
        st = build_statement(residential, statement_date=AS_OF, as_of=AS_OF)
        codes = {label: code for label, _a, code, _n in st["breakdown_lines"]}
        assert codes["Month Rent"] == "4110"

    def test_rent_line_uses_commercial_income_code(self, commercial):
        st = build_statement(commercial, statement_date=AS_OF, as_of=AS_OF)
        codes = {label: code for label, _a, code, _n in st["breakdown_lines"]}
        assert codes["Month Rent"] == "4120"

    def test_rent_plus_arrears_is_the_sum(self, residential):
        st = build_statement(residential, statement_date=AS_OF, as_of=AS_OF)
        # Month rent 12,000 + arrears b/f 8,000
        assert st["rent_plus_arrears"] == "20,000.00"


@pytest.mark.django_db
class TestChannelsAgree:
    def test_email_html_shows_codes(self, residential):
        from apps.payments.notifications import payment_statement_email_html

        st = build_statement(residential, statement_date=AS_OF, as_of=AS_OF)
        html = payment_statement_email_html(residential.full_name, Decimal("5000"), "R1", st)
        for label in EXPECTED_LINES:
            assert label in html
        assert "2100" in html and "1040" in html and "4150" in html

    def test_sms_includes_rent_plus_arrears(self, residential):
        from apps.payments.notifications import payment_sms_message

        st = build_statement(residential, statement_date=AS_OF, as_of=AS_OF)
        sms = payment_sms_message(residential.full_name, Decimal("5000"), "DON1A", "R1", st)
        assert "Rent + Arrears 20,000.00" in sms
        assert "Unpaid Balance" in sms

    def test_pdf_template_renders_the_coded_table(self, residential):
        from django.template.loader import render_to_string

        st = build_statement(residential, statement_date=AS_OF, as_of=AS_OF)
        html = render_to_string("payments/statement_pdf.html", st)
        for label in EXPECTED_LINES:
            assert label in html
        assert "2100" in html and "4110" in html
