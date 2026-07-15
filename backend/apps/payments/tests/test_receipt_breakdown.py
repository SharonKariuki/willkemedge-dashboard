"""
Tests for the payment-receipt statement totals (Day 5 · Feature 7).

Acceptance criterion: when a payment is recorded the tenant receives an SMS
AND email receipt carrying the five named totals —
    Security Deposit · Arrears Brought Forward · Month Rent ·
    Other Charges · Unpaid Balance.

We keep Barclay's official statement layout intact and add these as a distinct
"Receipt Breakdown" block (additive), so both channels agree on the figures.
"""
import datetime as _dt
from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.buildings.models import Building, Unit, UnitStatus
from apps.payments.models import (
    Arrears,
    Payment,
    PaymentSource,
    PaymentType,
    UtilityCharge,
)
from apps.tenants.models import Tenant, TenantStatus

AS_OF = _dt.date(2026, 4, 13)


@pytest.fixture
def tenant(db):
    building = Building.objects.create(name="Sunset Apartments", total_floors=2)
    unit = Unit.objects.create(
        building=building, label="B3", monthly_rent=Decimal("12000"),
        status=UnitStatus.OCCUPIED_UNPAID,
    )
    t = Tenant.objects.create(
        first_name="Peter", last_name="Kamau", id_number="98765432",
        phone="+254798765432", email="peter@example.com",
        unit=unit, monthly_rent=Decimal("12000"),
        move_in_date="2026-01-01", status=TenantStatus.ACTIVE,
    )
    # Prior-period rent still owed → Arrears Brought Forward = 8,000
    Arrears.objects.create(
        tenant=t, period_month=3, period_year=2026,
        expected_rent=Decimal("12000"), amount_paid=Decimal("4000"),
        balance=Decimal("8000"), is_cleared=False,
    )
    # Current period (April) rent obligation → Month Rent = 12,000
    Arrears.objects.create(
        tenant=t, period_month=4, period_year=2026,
        expected_rent=Decimal("12000"), amount_paid=Decimal("0"),
        balance=Decimal("12000"), is_cleared=False,
    )
    # Security deposit held = 12,000
    Payment.objects.create(
        tenant=t, amount=Decimal("12000"), payment_date="2026-01-01",
        period_month=1, period_year=2026, source=PaymentSource.MPESA,
        payment_type=PaymentType.DEPOSIT, reference="DEP_001",
    )
    # Other charges (water) = 1,500
    UtilityCharge.objects.create(
        tenant=t, posting_date="2026-04-05", period_month=4, period_year=2026,
        label="Water Usage", amount=Decimal("1500"),
    )
    return t


class TestStatementTotals:
    @pytest.mark.django_db
    def test_five_named_totals(self, tenant):
        from apps.payments.statement_service import build_statement

        st = build_statement(tenant, statement_date=AS_OF, as_of=AS_OF)
        assert st["security_deposit"] == "12,000.00"
        assert st["arrears_bf"] == "8,000.00"
        assert st["month_rent"] == "12,000.00"
        assert st["other_charges"] == "1,500.00"
        # Ledger: (12,000 + 12,000 + 1,500) invoiced − 12,000 deposit paid = 13,500
        assert st["unpaid_balance"] == "13,500.00"

    @pytest.mark.django_db
    def test_zero_when_no_records(self, tenant):
        """A fresh tenant with no arrears/deposit/utilities → all zero."""
        from apps.payments.statement_service import build_statement

        building = tenant.unit.building
        unit = Unit.objects.create(
            building=building, label="B4", monthly_rent=Decimal("9000"),
            status=UnitStatus.OCCUPIED_UNPAID,
        )
        fresh = Tenant.objects.create(
            first_name="New", last_name="Tenant", id_number="55667788",
            phone="+254755667788", unit=unit, monthly_rent=Decimal("9000"),
            move_in_date="2026-04-01", status=TenantStatus.ACTIVE,
        )
        st = build_statement(fresh, statement_date=AS_OF, as_of=AS_OF)
        assert st["security_deposit"] == "0.00"
        assert st["arrears_bf"] == "0.00"
        assert st["other_charges"] == "0.00"


class TestReceiptChannels:
    @pytest.mark.django_db
    @patch("apps.payments.notifications.send_sms")
    @patch("apps.payments.notifications.send_email")
    def test_sms_carries_the_five_totals(self, mock_email, mock_sms, tenant):
        from apps.payments.tasks import send_payment_confirmation

        pmt = Payment.objects.create(
            tenant=tenant, amount=Decimal("5000"), payment_date="2026-04-13",
            period_month=4, period_year=2026, source=PaymentSource.MPESA,
            reference="MPE_RENT_001",
        )
        send_payment_confirmation(pmt.id)

        sms = mock_sms.call_args[0][1]
        assert "Deposit 12,000.00" in sms
        assert "Arrears B/F 8,000.00" in sms
        assert "Month Rent 12,000.00" in sms
        assert "Other Charges 1,500.00" in sms
        assert "Unpaid Balance" in sms

    @pytest.mark.django_db
    def test_email_html_has_receipt_breakdown(self, tenant):
        from apps.payments.notifications import payment_statement_email_html
        from apps.payments.statement_service import build_statement

        st = build_statement(tenant, statement_date=AS_OF, as_of=AS_OF)
        html = payment_statement_email_html(tenant.full_name, Decimal("5000"), "REF1", st)
        assert "Receipt Breakdown" in html
        assert "Security Deposit" in html
        assert "Arrears Brought Forward" in html
        assert "Other Charges" in html
        assert "Rent + Arrears" in html
        assert "Unpaid Balance" in html
