"""The RESIDENTIAL cycle: invoiced on the 1st, payable by the 5th.

The landlord's instruction is that an ordinary tenant is billed for the month
they are living in, on the day it starts, and pays within the first five days —
not a month in advance. Commercial lettings keep the advance cycle, because the
arcade's VAT invoice has to arrive before the month it covers; that half is in
test_advance_statements.py.

So the roster is on two cycles at once, and the things that broke while this
was built are all about the seam between them:

  * the 25th must NOT roll a residential tenant forward — billed on the 25th
    for the month ahead, they would be carrying September's rent through the
    last week of August, a month of debt on the arrears report that nobody
    actually owes yet;
  * the 1st must not re-send to a commercial tenant, who was already emailed
    that same month's statement on the 25th — and must not skip a residential
    tenant on the grounds that "the run already went out";
  * one run has to serve both, because there is one scheduler and one job. The
    dedupe key is the month STATED, which is what lets each cycle take its own
    day and ignore the other's.
"""
import datetime as dt
from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.payments.billing_calendar import (
    RENT_DUE_DAY,
    billing_period,
    rent_due_date,
    tenant_billing_period,
)
from apps.payments.models import Arrears, NotificationStatus, TenantNotification
from apps.payments.statement_service import build_statement
from apps.payments.tasks import generate_monthly_arrears, send_monthly_statements
from apps.tenants.models import Tenant, TenantStatus

FIRST = dt.date(2026, 9, 1)      # the day the residential September run fires
RUN_DAY = dt.date(2026, 8, 25)   # the day the commercial September run fires
SEPTEMBER = (2026, 9)
AUGUST = (2026, 8)


@pytest.fixture(autouse=True)
def _smtp_configured(settings):
    settings.EMAIL_HOST_USER = "wilkem.ventures@gmail.com"
    settings.EMAIL_HOST_PASSWORD = "app-password"
    settings.TENANT_NOTIFICATIONS_ENABLED = True


@pytest.fixture
def building(db):
    return Building.objects.create(name="Road Block", total_floors=4)


def _tenant(building, *, label, classification, email="tenant@example.com",
            rent="20000", move_in="2026-07-01"):
    unit = Unit.objects.create(
        building=building, label=label, monthly_rent=Decimal(rent),
        status=UnitStatus.OCCUPIED_UNPAID, classification=classification,
    )
    return Tenant.objects.create(
        first_name="Sarah", last_name="Hamisi", id_number=f"ID-{label}",
        phone="+254726012481", email=email, unit=unit, due_day=RENT_DUE_DAY,
        monthly_rent=Decimal(rent), move_in_date=move_in,
        status=TenantStatus.ACTIVE,
    )


def _house(building, **kw):
    kw.setdefault("label", "RB101")
    return _tenant(building, classification=UnitClassification.RESIDENTIAL, **kw)


def _shop(building, **kw):
    kw.setdefault("label", "MCG05")
    return _tenant(building, classification=UnitClassification.BUSINESS, **kw)


def _periods(tenant):
    return set(
        Arrears.objects.filter(tenant=tenant)
        .values_list("period_year", "period_month")
    )


def _raise(tenant, year, month, rent="20000"):
    return Arrears.objects.create(
        tenant=tenant, period_month=month, period_year=year,
        expected_rent=Decimal(rent), expected_vat=Decimal("0"),
        amount_paid=Decimal("0"), balance=Decimal(rent), is_cleared=False,
    )


class TestWhichCycleATenantIsOn:
    def test_a_house_is_billed_for_the_month_it_is_in(self, building):
        assert tenant_billing_period(_house(building), FIRST) == SEPTEMBER

    def test_the_25th_does_not_roll_a_house_forward(self, building):
        """The whole point of the split. On 25 August an ordinary tenant is
        still on August — the month they are living in and have been billed
        for — while the arcade has already moved to September."""
        assert tenant_billing_period(_house(building), RUN_DAY) == AUGUST

    def test_the_25th_rolls_a_shop_forward(self, building):
        assert tenant_billing_period(_shop(building), RUN_DAY) == SEPTEMBER

    def test_a_tenancy_with_no_unit_falls_to_the_residential_cycle(self):
        """The default has to be the cycle almost everyone is on, not the
        exception, for anything holding a tenant with no unit resolved."""
        assert tenant_billing_period(object(), RUN_DAY) == AUGUST

    def test_the_calendar_helper_still_defaults_to_the_advance_cycle(self):
        """Callers that genuinely mean "the advance cycle" — the arcade
        reconciliation guards — keep working without passing a flag."""
        assert billing_period(RUN_DAY) == SEPTEMBER
        assert billing_period(RUN_DAY, advance=False) == AUGUST


class TestArrearsRaisedOnTheFirst:
    def test_the_first_raises_the_month_just_begun(self, building):
        tenant = _house(building)

        with patch("apps.payments.tasks.timezone.localdate", return_value=FIRST):
            generate_monthly_arrears()

        assert SEPTEMBER in _periods(tenant)

    def test_the_25th_does_not_bill_a_house_for_next_month(self, building):
        tenant = _house(building)

        with patch("apps.payments.tasks.timezone.localdate", return_value=RUN_DAY):
            generate_monthly_arrears()

        assert SEPTEMBER not in _periods(tenant)
        assert AUGUST in _periods(tenant)

    def test_one_run_bills_each_tenant_their_own_month(self, building):
        """The 25 August run: September for the arcade, August for the house.
        A single `through` for the whole roster cannot express this."""
        house = _house(building)
        shop = _shop(building, email="shop@example.com")

        with patch("apps.payments.tasks.timezone.localdate", return_value=RUN_DAY):
            generate_monthly_arrears()

        assert SEPTEMBER in _periods(shop)
        assert SEPTEMBER not in _periods(house)
        assert AUGUST in _periods(house)

    def test_the_first_catches_a_shop_up_when_the_25th_failed(self, building):
        """The 1st still bills every month a tenant is short of. A commercial
        statement cannot state a month that was never raised, so a failed 25th
        has to be repaired before the 1st's statement run goes out."""
        shop = _shop(building)

        with patch("apps.payments.tasks.timezone.localdate", return_value=FIRST):
            generate_monthly_arrears()

        assert SEPTEMBER in _periods(shop)
        assert AUGUST in _periods(shop)


class TestRentIsDueOnTheFifth:
    def test_the_statement_for_the_month_is_due_on_its_fifth(self, building):
        tenant = _house(building)
        _raise(tenant, 2026, 9)

        statement = build_statement(tenant, statement_date=FIRST, period=SEPTEMBER)

        assert statement["due_date"] == "5th September 2026"
        assert statement["statement_date"] == "1 September 2026"

    def test_both_cycles_land_on_the_same_due_date(self):
        """The two cycles differ in when the charge is RAISED, not in when it
        is payable. September rent is due 5 September for the arcade billed on
        25 August and for the house billed on 1 September alike."""
        assert rent_due_date(SEPTEMBER) == dt.date(2026, 9, 5)

    def test_a_short_month_cannot_produce_an_impossible_date(self):
        """due_day stays editable per letting and the form allows 31. Building
        date(2026, 2, 31) raises ValueError and takes a whole run down."""
        assert rent_due_date((2026, 2), due_day=31) == dt.date(2026, 2, 28)


class TestOneRunServesBothCycles:
    def test_the_first_emails_the_house_its_current_month(self, building):
        tenant = _house(building)

        with patch("apps.payments.tasks.timezone.localdate", return_value=FIRST):
            generate_monthly_arrears()
            with patch("apps.payments.notifications.send_email", return_value=True) as send:
                counts = send_monthly_statements()

        assert counts["sent"] == 1
        assert counts["periods"] == {"2026-09": 1}
        assert "September-2026" in send.call_args.args[2]
        assert TenantNotification.objects.get(tenant=tenant).dedupe_key == (
            f"statement:{tenant.id}:2026-09"
        )

    def test_the_25th_run_reaches_only_the_shop(self, building):
        """August already went out to the house on 1 August. Re-sending it as
        part of the arcade's run would be the second August statement they had
        received that month.

        Driven through a full cycle rather than set up by hand, because the
        steady state is the thing being asserted: the shop is emailed August on
        25 July, the house on 1 August, and each is skipped by the other's run.
        """
        house = _house(building, email="house@example.com")
        shop = _shop(building, email="shop@example.com")

        def _run(on):
            with patch("apps.payments.tasks.timezone.localdate", return_value=on):
                generate_monthly_arrears()
                with patch("apps.payments.notifications.send_email", return_value=True):
                    return send_monthly_statements()

        # The 25 July run states August for the shop and July for the house —
        # the house had no 1 July run in this fixture, so the safety net picks
        # them up on the month they are actually in. That is the behaviour
        # wanted: a missed run is a delay, not a skipped month.
        _run(dt.date(2026, 7, 25))
        august = _run(dt.date(2026, 8, 1))   # house: August; shop already sent
        september = _run(RUN_DAY)            # shop: September; house on August

        assert (august["sent"], august["skipped"]) == (1, 1)
        assert (september["sent"], september["skipped"]) == (1, 1)
        assert september["periods"] == {"2026-08": 1, "2026-09": 1}
        sent = set(
            TenantNotification.objects.filter(status=NotificationStatus.SENT)
            .values_list("tenant_id", "dedupe_key")
        )
        assert sent == {
            (house.id, f"statement:{house.id}:2026-07"),
            (shop.id, f"statement:{shop.id}:2026-08"),
            (house.id, f"statement:{house.id}:2026-08"),
            (shop.id, f"statement:{shop.id}:2026-09"),
        }

    def test_the_first_run_reaches_only_the_house(self, building):
        """The mirror image: the shop was emailed September on 25 August and
        must not be emailed it again on 1 September."""
        house = _house(building, email="house@example.com")
        shop = _shop(building, email="shop@example.com")

        with patch("apps.payments.tasks.timezone.localdate", return_value=RUN_DAY):
            generate_monthly_arrears()
            with patch("apps.payments.notifications.send_email", return_value=True):
                send_monthly_statements()

        with patch("apps.payments.tasks.timezone.localdate", return_value=FIRST):
            generate_monthly_arrears()
            with patch("apps.payments.notifications.send_email", return_value=True) as send:
                counts = send_monthly_statements()

        assert counts["sent"] == 1
        assert counts["skipped"] == 1
        assert send.call_count == 1
        assert TenantNotification.objects.filter(
            tenant=house, status=NotificationStatus.SENT,
            dedupe_key=f"statement:{house.id}:2026-09",
        ).exists()
        assert TenantNotification.objects.filter(
            tenant=shop, status=NotificationStatus.SENT
        ).count() == 1

    def test_an_explicit_month_still_re_issues_it_to_everybody(self, building):
        """`?period=2026-08` is an instruction about which month, not a hint.
        Falling back to each tenant's own cycle would quietly re-issue two
        different months and the office would have no way to ask for one."""
        _house(building, email="house@example.com")
        _shop(building, email="shop@example.com")

        with patch("apps.payments.notifications.send_email", return_value=True):
            counts = send_monthly_statements("2026-08")

        assert counts["periods"] == {"2026-08": 2}
        assert counts["sent"] == 2

    def test_a_manual_resend_gives_the_house_the_month_it_is_in(self, building):
        """The office re-sends on request. Handing a residential tenant next
        month's statement — the arcade's month — is the first thing they would
        report."""
        from apps.payments.statement_delivery import send_tenant_statement

        tenant = _house(building)
        _raise(tenant, 2026, 8)
        _raise(tenant, 2026, 9)

        with patch("django.utils.timezone.localdate", return_value=RUN_DAY), \
             patch("apps.payments.notifications.send_email", return_value=True) as send:
            note = send_tenant_statement(tenant, automatic=False)

        assert note.status == NotificationStatus.SENT
        assert "August-2026" in send.call_args.args[2]
