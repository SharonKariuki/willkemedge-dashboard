"""The invoice calendar: residential on the 28th, commercial on the 25th.

Every letting is invoiced a month ahead. The invoice for October's rent goes out
on 28 September for a house and on 25 September for a shop, carries the water
metered in September, and is payable by 5 October. The commercial half of the
advance mechanics is also in test_advance_statements.py.

Four dates, and the tests keep them apart:

  * generation date — the 25th or the 28th of the month before;
  * rent period     — the month after the one the invoice is sent in;
  * water period    — the month the invoice is sent in;
  * rent due date   — the 5th of the rent period.

The things that break at the seams:

  * the 25th must NOT roll a house forward — its month moves on the 28th;
  * each run reaches only the tenants whose day it is, and the catch-up on the
    1st sends nothing when both days worked — the dedupe key is the month
    STATED, which is what lets each day ignore the other's tenants;
  * September's water belongs to the OCTOBER invoice: it must be that
    invoice's Other Charges, not part of its brought-forward figure.
"""
import datetime as dt
from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.payments.billing_calendar import (
    RENT_DUE_DAY,
    billing_period,
    invoice_date,
    rent_due_date,
    tenant_billing_period,
)
from apps.payments.meter_service import bill_meter_reading
from apps.payments.models import Arrears, NotificationStatus, TenantNotification, UtilityCharge
from apps.payments.statement_service import build_statement
from apps.payments.tasks import generate_monthly_arrears, send_monthly_statements
from apps.tenants.models import Tenant, TenantStatus

COMMERCIAL_DAY = dt.date(2026, 9, 25)   # shops are invoiced for October
RESIDENTIAL_DAY = dt.date(2026, 9, 28)  # houses are invoiced for October
CATCH_UP = dt.date(2026, 10, 1)
OCTOBER = (2026, 10)
SEPTEMBER = (2026, 9)
AUGUST = (2026, 8)


@pytest.fixture(autouse=True)
def _smtp_configured(settings):
    settings.EMAIL_HOST_USER = "wilkem.ventures@gmail.com"
    settings.EMAIL_HOST_PASSWORD = "app-password"
    settings.TENANT_NOTIFICATIONS_ENABLED = True


@pytest.fixture
def building(db):
    return Building.objects.create(
        name="Road Block", total_floors=4, water_rate_per_unit=Decimal("150"),
    )


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


def _read(tenant, period, closing, opening=None):
    return bill_meter_reading(
        tenant=tenant, period_year=period[0], period_month=period[1],
        closing_reading=Decimal(closing),
        opening_reading=Decimal(opening) if opening is not None else None,
    )


def _d(text):
    return Decimal(text.replace(",", "")) if text else Decimal("0")


def _run(on):
    with patch("apps.payments.tasks.timezone.localdate", return_value=on):
        generate_monthly_arrears()
        with patch("apps.payments.notifications.send_email", return_value=True):
            return send_monthly_statements()


class TestWhichMonthATenantIsOn:
    def test_a_house_stays_on_this_month_until_the_28th(self, building):
        house = _house(building)
        assert tenant_billing_period(house, dt.date(2026, 9, 27)) == SEPTEMBER
        assert tenant_billing_period(house, RESIDENTIAL_DAY) == OCTOBER
        assert tenant_billing_period(house, dt.date(2026, 9, 30)) == OCTOBER

    def test_the_25th_does_not_roll_a_house_forward(self, building):
        assert tenant_billing_period(_house(building), COMMERCIAL_DAY) == SEPTEMBER

    def test_the_25th_rolls_a_shop_forward(self, building):
        assert tenant_billing_period(_shop(building), COMMERCIAL_DAY) == OCTOBER

    def test_a_tenancy_with_no_unit_is_on_the_residential_day(self):
        """The default has to be the day almost everyone is on."""
        assert tenant_billing_period(object(), dt.date(2026, 9, 27)) == SEPTEMBER
        assert tenant_billing_period(object(), RESIDENTIAL_DAY) == OCTOBER

    def test_february_28th_invoices_march(self, building):
        assert tenant_billing_period(_house(building), dt.date(2027, 2, 28)) == (2027, 3)

    def test_december_28th_invoices_the_new_year(self, building):
        assert tenant_billing_period(_house(building), dt.date(2026, 12, 28)) == (2027, 1)

    def test_the_calendar_helper_defaults_to_the_commercial_day(self):
        """Callers that ask without a tenant — the arcade reconciliation
        guards — keep getting the commercial answer."""
        assert billing_period(COMMERCIAL_DAY) == OCTOBER
        assert billing_period(COMMERCIAL_DAY, run_day=28) == SEPTEMBER

    def test_each_letting_is_invoiced_on_its_own_day(self, building):
        assert invoice_date(_house(building), OCTOBER) == RESIDENTIAL_DAY
        assert invoice_date(_shop(building), OCTOBER) == COMMERCIAL_DAY
        assert invoice_date(_house(building, label="RB102"), (2027, 1)) == dt.date(2026, 12, 28)


class TestRentIsRaisedOnTheInvoiceDay:
    def test_the_28th_raises_next_month_for_a_house(self, building):
        house = _house(building)

        with patch("apps.payments.tasks.timezone.localdate", return_value=RESIDENTIAL_DAY):
            generate_monthly_arrears()

        assert OCTOBER in _periods(house)

    def test_the_25th_raises_the_shop_but_not_the_house(self, building):
        house = _house(building)
        shop = _shop(building, email="shop@example.com")

        with patch("apps.payments.tasks.timezone.localdate", return_value=COMMERCIAL_DAY):
            generate_monthly_arrears()

        assert OCTOBER in _periods(shop)
        assert OCTOBER not in _periods(house)
        assert SEPTEMBER in _periods(house)

    def test_the_first_catches_up_a_house_when_the_28th_failed(self, building):
        house = _house(building)

        with patch("apps.payments.tasks.timezone.localdate", return_value=CATCH_UP):
            generate_monthly_arrears()

        assert OCTOBER in _periods(house)

    def test_rerunning_the_28th_raises_nothing_twice(self, building):
        house = _house(building)

        with patch("apps.payments.tasks.timezone.localdate", return_value=RESIDENTIAL_DAY):
            generate_monthly_arrears()
            assert generate_monthly_arrears() == 0

        assert Arrears.objects.filter(tenant=house, period_year=2026, period_month=10).count() == 1


class TestTheInvoiceDates:
    def test_october_is_due_on_the_fifth_of_october(self, building):
        house = _house(building)
        _raise(house, 2026, 10)

        statement = build_statement(house, statement_date=RESIDENTIAL_DAY, period=OCTOBER)

        assert statement["due_date"] == "5th October 2026"
        assert statement["statement_date"] == "28 Sept 2026"
        assert statement["current_period_label"] == "October-2026"

    def test_both_lettings_land_on_the_same_due_date(self):
        assert rent_due_date(OCTOBER) == dt.date(2026, 10, 5)

    def test_a_short_month_cannot_produce_an_impossible_date(self):
        assert rent_due_date((2026, 2), due_day=31) == dt.date(2026, 2, 28)

    def test_rent_is_shown_raised_on_the_invoice_day(self, building):
        house = _house(building)
        shop = _shop(building)
        for tenant in (house, shop):
            _raise(tenant, 2026, 10)

        def _rent_row(tenant):
            st = build_statement(tenant, statement_date=RESIDENTIAL_DAY, period=OCTOBER)
            return next(r for r in st["rows"] if r["description"].startswith("Month Rent"))

        assert _rent_row(house)["posting_date"] == "28 Sept 2026"
        assert _rent_row(shop)["posting_date"] == "25 Sept 2026"

    def test_a_first_month_is_never_shown_before_the_move_in(self, building):
        house = _house(building, move_in="2026-10-03")
        _raise(house, 2026, 10)

        st = build_statement(house, statement_date=dt.date(2026, 10, 3), period=OCTOBER)
        row = next(r for r in st["rows"] if r["description"].startswith("Month Rent"))

        assert row["posting_date"] == "3 Oct 2026"


class TestWaterRidesOnTheNextInvoice:
    def test_a_reading_posts_on_the_invoice_day(self, building):
        house = _house(building)
        shop = _shop(building)

        assert _read(house, SEPTEMBER, "110", opening="100").posting_date == RESIDENTIAL_DAY
        assert _read(shop, SEPTEMBER, "210", opening="200").posting_date == COMMERCIAL_DAY

    def test_the_october_invoice_carries_septembers_water(self, building):
        house = _house(building)
        _raise(house, 2026, 9)
        _raise(house, 2026, 10)
        _read(house, AUGUST, "108", opening="100")      # 8 units  -> 1,200
        _read(house, SEPTEMBER, "118")                  # 10 units -> 1,500

        st = build_statement(house, statement_date=RESIDENTIAL_DAY, period=OCTOBER)

        # September's water is this invoice's ...
        assert st["other_charges"] == "1,500.00"
        # ... and what is brought forward is September's rent with the water
        # that rode on September's invoice, August's.
        assert st["arrears_bf"] == "21,200.00"
        assert st["month_rent"] == "20,000.00"
        assert _d(st["arrears_bf"]) + _d(st["month_rent"]) + _d(st["other_charges"]) == _d(
            st["unpaid_balance"]
        )

    def test_the_commercial_invoice_carries_the_same_months_water(self, building):
        shop = _shop(building)
        _raise(shop, 2026, 10)
        _read(shop, SEPTEMBER, "210", opening="200")

        st = build_statement(shop, statement_date=COMMERCIAL_DAY, period=OCTOBER)

        assert st["other_charges"] == "1,500.00"

    def test_no_water_line_is_dated_after_the_invoice(self, building):
        house = _house(building)
        _raise(house, 2026, 10)
        _read(house, SEPTEMBER, "110", opening="100")

        st = build_statement(house, statement_date=RESIDENTIAL_DAY, period=OCTOBER)
        water = next(r for r in st["rows"] if r["description"].startswith("Water"))

        assert water["posting_date"] == "28 Sept 2026"

    def test_a_one_off_charge_stays_on_its_own_months_invoice(self, building):
        """Only metered usage moves. A charge a landlord sheet posted against
        September belongs to September's invoice, so by October it is part of
        what is brought forward."""
        house = _house(building)
        _raise(house, 2026, 9)
        _raise(house, 2026, 10)
        UtilityCharge.objects.create(
            tenant=house, posting_date=dt.date(2026, 9, 1), period_year=2026,
            period_month=9, label="Other costs", amount=Decimal("700"),
        )

        st = build_statement(house, statement_date=RESIDENTIAL_DAY, period=OCTOBER)

        assert st["other_charges"] == "0.00"
        assert st["arrears_bf"] == "20,700.00"


class TestMissingWaterReadings:
    def test_a_read_meter_with_no_reading_is_flagged_and_still_invoiced(self, building):
        house = _house(building)
        _read(house, AUGUST, "108", opening="100")

        counts = _run(RESIDENTIAL_DAY)

        assert counts["sent"] == 1
        assert counts["missing_water"] == ["RB101"]

    def test_a_meter_read_for_the_month_is_not_flagged(self, building):
        house = _house(building)
        _read(house, AUGUST, "108", opening="100")
        _read(house, SEPTEMBER, "118")

        assert _run(RESIDENTIAL_DAY)["missing_water"] == []

    def test_a_unit_that_has_never_been_read_is_not_flagged(self, building):
        _house(building)

        assert _run(RESIDENTIAL_DAY)["missing_water"] == []

    def test_a_tenant_already_sent_is_not_flagged_again(self, building):
        """The 1st re-runs the whole roster. Listing every house again there
        would make the catch-up look like a second missed month."""
        house = _house(building)
        _read(house, AUGUST, "108", opening="100")

        assert _run(RESIDENTIAL_DAY)["missing_water"] == ["RB101"]
        assert _run(CATCH_UP)["missing_water"] == []


class TestOneRunServesBothDays:
    def test_each_day_reaches_only_its_own_tenants(self, building):
        """Driven through a full month so the steady state is what is
        asserted: each run sends to the tenants whose day it is, and skips
        the rest as already sent."""
        house = _house(building, email="house@example.com")
        shop = _shop(building, email="shop@example.com")

        _run(dt.date(2026, 8, 25))       # shop: September; house: August
        _run(dt.date(2026, 8, 28))       # house: September; shop already sent
        commercial = _run(COMMERCIAL_DAY)   # shop: October; house already sent
        residential = _run(RESIDENTIAL_DAY)  # house: October; shop already sent
        catch_up = _run(CATCH_UP)        # nothing new

        assert (commercial["sent"], commercial["skipped"]) == (1, 1)
        assert commercial["periods"] == {"2026-09": 1, "2026-10": 1}
        assert (residential["sent"], residential["skipped"]) == (1, 1)
        assert residential["periods"] == {"2026-10": 2}
        assert (catch_up["sent"], catch_up["skipped"]) == (0, 2)

        sent = set(
            TenantNotification.objects.filter(status=NotificationStatus.SENT, channel="email")
            .values_list("tenant_id", "dedupe_key")
        )
        assert sent == {
            (house.id, f"statement:{house.id}:2026-08"),
            (shop.id, f"statement:{shop.id}:2026-09"),
            (house.id, f"statement:{house.id}:2026-09"),
            (shop.id, f"statement:{shop.id}:2026-10"),
            (house.id, f"statement:{house.id}:2026-10"),
        }

    def test_the_first_sends_a_house_its_invoice_when_the_28th_failed(self, building):
        house = _house(building)

        counts = _run(CATCH_UP)

        assert counts["sent"] == 1
        assert counts["periods"] == {"2026-10": 1}
        assert TenantNotification.objects.filter(
            tenant=house, status=NotificationStatus.SENT,
            dedupe_key=f"statement:{house.id}:2026-10",
        ).exists()

    def test_an_explicit_month_still_re_issues_it_to_everybody(self, building):
        """`?period=2026-09` is an instruction about which month, not a hint."""
        _house(building, email="house@example.com")
        _shop(building, email="shop@example.com")

        with patch("apps.payments.notifications.send_email", return_value=True):
            counts = send_monthly_statements("2026-09")

        assert counts["periods"] == {"2026-09": 2}
        assert counts["sent"] == 2

    @pytest.mark.parametrize("today, month", [
        (dt.date(2026, 9, 26), "September-2026"),
        (RESIDENTIAL_DAY, "October-2026"),
    ])
    def test_a_manual_resend_matches_the_houses_invoice_day(self, building, today, month):
        from apps.payments.statement_delivery import send_tenant_statement

        house = _house(building)
        _raise(house, 2026, 9)
        _raise(house, 2026, 10)

        with patch("django.utils.timezone.localdate", return_value=today), \
             patch("apps.payments.notifications.send_email", return_value=True) as send:
            note = send_tenant_statement(house, automatic=False)

        assert note.status == NotificationStatus.SENT
        assert month in send.call_args.args[2]
