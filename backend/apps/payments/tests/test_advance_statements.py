"""Statements go out on the 25th, for the month that has not started yet.

Tenants asked to be billed before the month begins rather than after it is
already running, so the cycle moved a month ahead of the calendar: on
25 August 2026 the system raises September's rent and emails September's
statement. See apps/payments/billing_calendar.py.

The three things that have to hold together, and each of which broke the
feature on its own while it was being built:

  * the charge exists before the statement states it — billing on the 1st and
    stating on the 2nd cannot produce a statement for a month that has not
    started;
  * the statement says September, not August — "current month" used to be
    clamped to the month the statement was drawn in;
  * September is charged, not overdue — every debt figure has to stop at the
    current calendar month, or the whole roster reads a month in arrears for
    the last week of every month.
"""
import datetime as dt
from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.buildings.models import Building, Unit, UnitStatus
from apps.payments.aging import aging_buckets
from apps.payments.billing_calendar import billing_period, statement_run_day
from apps.payments.models import (
    Arrears,
    NotificationStatus,
    Payment,
    PaymentType,
    TenantNotification,
)
from apps.payments.monthly_ledger import current_balance
from apps.payments.notification_services import _current_balance
from apps.payments.statement_service import build_statement
from apps.payments.tasks import generate_monthly_arrears, send_monthly_statements
from apps.tenants.models import Tenant, TenantStatus

RUN_DAY = dt.date(2026, 8, 25)   # the day the September run fires
SEPTEMBER = (2026, 9)


@pytest.fixture(autouse=True)
def _smtp_configured(settings):
    settings.EMAIL_HOST_USER = "wilkem.ventures@gmail.com"
    settings.EMAIL_HOST_PASSWORD = "app-password"
    settings.TENANT_NOTIFICATIONS_ENABLED = True


@pytest.fixture
def building(db):
    return Building.objects.create(name="Road Block", total_floors=4)


def _make_tenant(building, *, rent="20000", label="RB101", email="tenant@example.com"):
    unit = Unit.objects.create(
        building=building, label=label, monthly_rent=Decimal(rent),
        status=UnitStatus.OCCUPIED_UNPAID,
    )
    return Tenant.objects.create(
        first_name="Sarah", last_name="Hamisi", id_number=f"ID-{label}",
        phone="+254726012481", email=email, unit=unit, due_day=5,
        monthly_rent=Decimal(rent), move_in_date="2026-07-01",
        status=TenantStatus.ACTIVE,
    )


def _raise(tenant, year, month, rent="20000"):
    return Arrears.objects.create(
        tenant=tenant, period_month=month, period_year=year,
        expected_rent=Decimal(rent), expected_vat=Decimal("0"),
        amount_paid=Decimal("0"), balance=Decimal(rent), is_cleared=False,
    )


class TestBillingPeriod:
    def test_the_run_day_bills_next_month(self):
        assert billing_period(dt.date(2026, 8, 25)) == (2026, 9)

    def test_the_day_before_still_bills_this_month(self):
        assert billing_period(dt.date(2026, 8, 24)) == (2026, 8)

    def test_the_rest_of_the_month_stays_on_next_month(self):
        """The cycle rolls forward once and stays there — a re-run on the 27th
        must not fall back to August and re-state a month already sent."""
        assert billing_period(dt.date(2026, 8, 31)) == (2026, 9)

    def test_december_rolls_into_the_new_year(self):
        assert billing_period(dt.date(2026, 12, 25)) == (2027, 1)

    def test_the_run_day_is_clamped_into_every_month(self, settings):
        """A run day of 31 would silently never fire in February."""
        settings.STATEMENT_RUN_DAY = 31
        assert statement_run_day() == 28
        settings.STATEMENT_RUN_DAY = "nonsense"
        assert statement_run_day() == 25


class TestArrearsRaisedInAdvance:
    def test_the_run_day_raises_next_month(self, building):
        tenant = _make_tenant(building)

        with patch("apps.payments.tasks.timezone.localdate", return_value=RUN_DAY):
            generate_monthly_arrears()

        periods = set(
            Arrears.objects.filter(tenant=tenant)
            .values_list("period_year", "period_month")
        )
        assert SEPTEMBER in periods, "September was never raised, so the 25th has nothing to state"

    def test_before_the_run_day_next_month_is_not_raised(self, building):
        tenant = _make_tenant(building)

        with patch("apps.payments.tasks.timezone.localdate",
                   return_value=dt.date(2026, 8, 24)):
            generate_monthly_arrears()

        periods = set(
            Arrears.objects.filter(tenant=tenant)
            .values_list("period_year", "period_month")
        )
        assert SEPTEMBER not in periods
        assert (2026, 8) in periods


class TestAdvanceStatementContent:
    def test_the_statement_drawn_on_the_25th_states_next_month(self, building):
        tenant = _make_tenant(building)
        _raise(tenant, 2026, 8)
        _raise(tenant, 2026, 9)

        statement = build_statement(tenant, statement_date=RUN_DAY, period=SEPTEMBER)

        assert statement["current_period_label"] == "September-2026"
        assert statement["statement_date"] == "25 Aug 2026"

    def test_rent_is_due_in_the_month_being_billed(self, building):
        """September rent is due on the 5th of September, not October. The due
        date used to be read off the month after the statement date, which said
        the same thing only while statements were issued in arrears."""
        tenant = _make_tenant(building)
        _raise(tenant, 2026, 9)

        statement = build_statement(tenant, statement_date=RUN_DAY, period=SEPTEMBER)

        assert statement["due_date"] == "5th September 2026"

    def test_august_is_carried_as_the_balance_brought_forward(self, building):
        tenant = _make_tenant(building)
        _raise(tenant, 2026, 8)
        _raise(tenant, 2026, 9)

        statement = build_statement(tenant, statement_date=RUN_DAY, period=SEPTEMBER)

        # August's unpaid 20,000 is what September opens on; September's own
        # 20,000 is the current month; the two together are what is owed.
        assert statement["arrears_bf"] == "20,000.00"
        assert statement["current_month_rent"] == "20,000.00"
        assert statement["total_due"] == "40,000.00"

    def test_the_summary_still_foots_to_the_ledger(self, building):
        """arrears + rent + VAT - payments must equal the closing balance, the
        identity the whole statement rests on, with the month stated in advance."""
        tenant = _make_tenant(building)
        _raise(tenant, 2026, 8)
        _raise(tenant, 2026, 9)
        Payment.objects.create(
            tenant=tenant, amount=Decimal("12000"), payment_date=dt.date(2026, 8, 10),
            period_month=8, period_year=2026,
            payment_type=PaymentType.RENT, reference="RB101-AUG",
        )

        statement = build_statement(tenant, statement_date=RUN_DAY, period=SEPTEMBER)

        def _num(value):
            return Decimal(value.replace(",", ""))

        footed = (
            _num(statement["arrears_others"])
            + _num(statement["current_month_rent"])
            + _num(statement["vat_on_rent"])
            - _num(statement["payments_received"])
        )
        assert footed == _num(statement["total_due"])

    def test_without_a_period_the_statement_is_about_its_own_month(self, building):
        """build_statement stays a plain 'as at this date' builder. The receipt
        path passes as_of to cut the ledger short and must keep getting the
        month it cut to, not the month the cycle has moved on to."""
        tenant = _make_tenant(building)
        _raise(tenant, 2026, 8)
        _raise(tenant, 2026, 9)

        statement = build_statement(
            tenant, statement_date=RUN_DAY, as_of=RUN_DAY
        )

        assert statement["current_period_label"] == "August-2026"


class TestAdvanceStatementRun:
    def test_the_run_emails_next_months_statement(self, building):
        tenant = _make_tenant(building)
        _raise(tenant, 2026, 8)

        with patch("apps.payments.tasks.timezone.localdate", return_value=RUN_DAY):
            generate_monthly_arrears()
            with patch("apps.payments.notifications.send_email", return_value=True) as send:
                counts = send_monthly_statements()

        assert counts["period"] == "2026-09"
        assert counts["as_at"] == "2026-08-25"
        assert counts["sent"] == 1
        html = send.call_args.args[2]
        assert "September-2026" in html

        note = TenantNotification.objects.get(tenant=tenant)
        assert note.dedupe_key == f"statement:{tenant.id}:2026-09"

    def test_the_september_run_is_not_swallowed_as_an_august_duplicate(self, building):
        """Both runs happen in August. Keyed on the send date rather than the
        month stated, the second would dedupe against the first and no tenant
        would ever receive a September statement."""
        tenant = _make_tenant(building)
        _raise(tenant, 2026, 8)
        _raise(tenant, 2026, 9)

        with patch("apps.payments.notifications.send_email", return_value=True) as send:
            with patch("apps.payments.tasks.timezone.localdate",
                       return_value=dt.date(2026, 8, 20)):
                august = send_monthly_statements()
            with patch("apps.payments.tasks.timezone.localdate", return_value=RUN_DAY):
                september = send_monthly_statements()

        assert august["period"] == "2026-08"
        assert september["period"] == "2026-09"
        assert august["sent"] == 1 and september["sent"] == 1
        assert send.call_count == 2
        assert set(
            TenantNotification.objects.filter(tenant=tenant).values_list(
                "dedupe_key", flat=True
            )
        ) == {f"statement:{tenant.id}:2026-08", f"statement:{tenant.id}:2026-09"}

    def test_rerunning_the_25th_does_not_send_september_twice(self, building):
        tenant = _make_tenant(building)
        _raise(tenant, 2026, 9)

        with patch("apps.payments.tasks.timezone.localdate", return_value=RUN_DAY), \
             patch("apps.payments.notifications.send_email", return_value=True) as send:
            first = send_monthly_statements()
            second = send_monthly_statements()

        assert first["sent"] == 1
        assert second["skipped"] == 1
        assert send.call_count == 1

    def test_a_manual_resend_matches_what_the_run_emailed(self, building):
        """The office re-sends on request. Getting August back after the tenant
        was emailed September is the first thing they would report."""
        from apps.payments.statement_delivery import send_tenant_statement

        tenant = _make_tenant(building)
        _raise(tenant, 2026, 8)
        _raise(tenant, 2026, 9)

        with patch("django.utils.timezone.localdate", return_value=RUN_DAY), \
             patch("apps.payments.notifications.send_email", return_value=True) as send:
            note = send_tenant_statement(tenant, automatic=False)

        assert note.status == NotificationStatus.SENT
        assert "September-2026" in send.call_args.args[2]


class TestAdvanceChargeIsNotOverdue:
    """September is raised on 25 August. Nothing that reports debt may count it
    until September actually starts."""

    def test_the_rent_roll_ignores_next_month(self, building):
        tenant = _make_tenant(building)
        _raise(tenant, 2026, 8)
        _raise(tenant, 2026, 9)

        assert current_balance(tenant, today=RUN_DAY) == Decimal("20000.00")

    def test_the_aging_table_ignores_next_month(self, building):
        tenant = _make_tenant(building)
        _raise(tenant, 2026, 8)
        _raise(tenant, 2026, 9)

        buckets = aging_buckets([tenant], today=RUN_DAY)

        assert buckets[tenant.id]["total"] == Decimal("20000.00")

    def test_the_reminder_sms_quotes_a_balance_that_excludes_next_month(self, building):
        """{balance} in a reminder used to sum every open arrears row. From the
        25th that is a month's rent too high for every tenant on the roster."""
        tenant = _make_tenant(building)
        _raise(tenant, 2026, 8)
        _raise(tenant, 2026, 9)

        with patch("apps.payments.notification_services.timezone.localdate",
                   return_value=RUN_DAY):
            assert _current_balance(tenant) == Decimal("20000")

    def test_the_unit_status_sweep_ignores_next_month(self, building):
        """The roster's arrears badge asks this question. September raised on
        25 August must not turn every occupied unit red."""
        from apps.buildings.services import has_unsettled_earlier_months

        tenant = _make_tenant(building)
        _raise(tenant, 2026, 9)

        with patch("django.utils.timezone.localdate", return_value=RUN_DAY):
            assert has_unsettled_earlier_months(tenant.unit) is False
