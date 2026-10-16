"""
Water and other charges on the tenant statement, and the balance-only messages.

Covers:
  - a negative utility row is printed as a credit in the payments column, not
    as water billed at a negative price, and the balance does not move
  - "Other Charges" is the invoice being stated: metered water rides on the
    NEXT month's invoice, so August's statement carries July's water, and
    June's is already inside Arrears Brought Forward and must not be counted a
    second time
  - "Other Charges" is never negative; a credit is reported on its own line
  - the statement SMS and email carry a summary whose lines add up to the
    unpaid balance, with no second total that reads like the amount to pay
"""
import datetime as _dt
from decimal import Decimal

import pytest

from apps.buildings.models import Building, Unit, UnitStatus
from apps.payments.models import Arrears, Payment, PaymentSource, UtilityCharge
from apps.payments.notifications import statement_sms_message, statement_summary_email_html
from apps.payments.statement_service import build_statement
from apps.tenants.models import Tenant, TenantStatus

AS_OF = _dt.date(2026, 8, 21)


@pytest.fixture
def tenant(db):
    building = Building.objects.create(name="Wilkem Edge Apartments", total_floors=4)
    unit = Unit.objects.create(
        building=building, label="DON2B", monthly_rent=Decimal("20000"),
        status=UnitStatus.OCCUPIED_UNPAID,
    )
    t = Tenant.objects.create(
        first_name="Emmah", last_name="Mueni", id_number="E1",
        phone="+254702723537", email="emmah@example.com", unit=unit,
        monthly_rent=Decimal("20000"), move_in_date="2026-01-01",
        status=TenantStatus.ACTIVE,
    )
    for month in (7, 8):
        Arrears.objects.create(
            tenant=t, period_month=month, period_year=2026,
            expected_rent=Decimal("20000"), amount_paid=Decimal("0"),
            balance=Decimal("20000"), is_cleared=False,
        )
    return t


def _water(tenant, month, amount, label="Water Usage"):
    return UtilityCharge.objects.create(
        tenant=tenant, posting_date=_dt.date(2026, month, 5),
        period_month=month, period_year=2026, label=label, amount=Decimal(amount),
    )


def _d(text):
    return Decimal(text.replace(",", "")) if text else Decimal("0")


class TestCreditsAreNotNegativeWater:
    def test_a_credit_is_printed_in_the_payments_column(self, tenant):
        _water(tenant, 8, "-2096", label="Water + Other Costs")

        st = build_statement(tenant, statement_date=AS_OF, as_of=AS_OF)

        row = next(r for r in st["rows"] if "Water + Other Costs" in r["description"])
        assert row["description"].startswith("Credit - ")
        assert row["invoice_amount"] == "", "a credit must not sit in the invoice column"
        assert row["payment"] == "2,096"

    def test_moving_the_credit_does_not_change_the_balance(self, tenant):
        _water(tenant, 8, "-2096", label="Water + Other Costs")

        st = build_statement(tenant, statement_date=AS_OF, as_of=AS_OF)

        # July 20,000 + August 20,000 - 2,096 credit.
        assert st["unpaid_balance"] == "37,904.00"
        assert _d(st["rows"][-1]["balance"]) == Decimal("37904")

    def test_other_charges_is_never_negative(self, tenant):
        _water(tenant, 8, "-2096", label="Water + Other Costs")

        st = build_statement(tenant, statement_date=AS_OF, as_of=AS_OF)

        assert st["other_charges"] == "0.00"
        assert st["other_credits"] == "2,096.00"
        lines = {label: amount for label, amount, _c, _n in st["breakdown_lines"]}
        assert lines["Other Charges"] == "0.00"
        assert lines["Less: Credits"] == "(2,096.00)"

    def test_no_credit_line_when_there_is_no_credit(self, tenant):
        _water(tenant, 8, "1500")

        st = build_statement(tenant, statement_date=AS_OF, as_of=AS_OF)

        assert "Less: Credits" not in [line[0] for line in st["breakdown_lines"]]
        assert st["other_credits_value"] == Decimal("0")

    def test_a_downward_correction_is_also_a_credit(self, tenant):
        """Reconcile posts an over-read as a negative balancing line."""
        _water(tenant, 8, "2000")
        _water(tenant, 8, "-500", label="Water Usage - statement adjustment")

        st = build_statement(tenant, statement_date=AS_OF, as_of=AS_OF)

        assert st["other_charges"] == "2,000.00"
        assert st["other_credits"] == "500.00"
        assert not [r for r in st["rows"] if r["invoice_amount"].startswith("-")]


class TestOtherChargesIsTheBilledPeriod:
    def test_last_months_water_is_not_counted_twice(self, tenant):
        _water(tenant, 6, "1200")
        _water(tenant, 7, "1500")

        st = build_statement(tenant, statement_date=AS_OF, as_of=AS_OF)

        # June's water rode on July's invoice, so it is inside Arrears B/F
        # with July's rent ...
        assert st["arrears_bf"] == "21,200.00"
        # ... and Other Charges is July's water, which August's invoice carries.
        assert st["other_charges"] == "1,500.00"
        # And the parts add back up to the balance.
        assert _d(st["arrears_bf"]) + _d(st["month_rent"]) + _d(st["other_charges"]) == _d(
            st["unpaid_balance"]
        )

    def test_with_no_rent_period_every_charge_counts(self, db):
        """Nothing is brought forward, so there is nothing to double-count."""
        building = Building.objects.create(name="Fresh", total_floors=1)
        unit = Unit.objects.create(
            building=building, label="F1", monthly_rent=Decimal("9000"),
            status=UnitStatus.OCCUPIED_UNPAID,
        )
        fresh = Tenant.objects.create(
            first_name="New", last_name="Tenant", id_number="F1", phone="+254700000001",
            unit=unit, monthly_rent=Decimal("9000"), move_in_date="2026-06-01",
            status=TenantStatus.ACTIVE,
        )
        _water(fresh, 6, "900")
        _water(fresh, 7, "1100")

        st = build_statement(fresh, statement_date=AS_OF, as_of=AS_OF)

        assert st["other_charges"] == "2,000.00"


class TestMessagesCarryASummary:
    def test_sms_itemises_and_ends_on_the_unpaid_balance(self, tenant):
        _water(tenant, 8, "-2096", label="Water + Other Costs")
        st = build_statement(tenant, statement_date=AS_OF, as_of=AS_OF)

        sms = statement_sms_message(tenant.full_name, tenant.unit.label, st)

        assert "Arrears B/F 20,000.00" in sms
        assert "Month Rent 20,000.00" in sms
        assert "Less Credits 2,096.00" in sms
        assert "Unpaid Balance 37,904.00, due by" in sms
        for dropped in ("Deposit", "Rent + Arrears", "Total Rent Due", "-2,096"):
            assert dropped not in sms, f"{dropped!r} should not be in the statement SMS"

    def test_nil_lines_are_left_out(self, tenant):
        st = build_statement(tenant, statement_date=AS_OF, as_of=AS_OF)

        sms = statement_sms_message(tenant.full_name, tenant.unit.label, st)

        for nil in ("Other Charges", "Less Credits", "Less Paid", "VAT"):
            assert nil not in sms

    def test_the_summary_lines_add_up_to_the_unpaid_balance(self, tenant):
        """The one thing a summary must never do is not add up."""
        _water(tenant, 6, "1200")
        _water(tenant, 7, "1500")
        _water(tenant, 8, "-300", label="Water Usage - statement adjustment")
        Payment.objects.create(
            tenant=tenant, amount=Decimal("5000"), payment_date="2026-08-10",
            period_month=8, period_year=2026, source=PaymentSource.MPESA,
            reference="AUG-PART",
        )
        st = build_statement(tenant, statement_date=AS_OF, as_of=AS_OF)

        sms = statement_sms_message(tenant.full_name, tenant.unit.label, st)

        for line in ("Arrears B/F 21,200.00", "Month Rent 20,000.00", "Other Charges 1,500.00",
                     "Less Credits 300.00", "Less Paid 5,000.00", "Unpaid Balance 37,400.00"):
            assert line in sms
        assert (
            _d(st["arrears_bf"]) + _d(st["month_rent"]) + _d(st["other_charges"])
            - _d(st["other_credits"]) - _d(st["payments_received"])
        ) == _d(st["unpaid_balance"])

    def test_email_body_carries_the_same_summary(self, tenant):
        _water(tenant, 8, "1500")
        st = build_statement(tenant, statement_date=AS_OF, as_of=AS_OF)

        html = statement_summary_email_html(tenant.full_name, st)

        assert "UNPAID BALANCE" in html
        assert "KES 41,500.00" in html
        assert "Arrears Brought Forward" in html
        assert "Other Charges (water etc.)" in html
        assert "How to pay" in html
        assert "attached" in html
        for dropped in ("Rent + Arrears", "Total Rent Due", "Security Deposit", "Posting Date"):
            assert dropped not in html
