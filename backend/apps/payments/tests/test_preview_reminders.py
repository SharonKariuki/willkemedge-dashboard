"""The reminder preflight must never become the thing it previews.

Its whole purpose is to be safe to run against production, so the property
worth pinning is the negative one: it sends no SMS, writes no notification
row, and touches nothing. The counts are checked too, because a preflight that
under-reports is worse than none.
"""
import datetime as dt
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command

from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.payments.models import Arrears, TenantNotification
from apps.tenants.models import Tenant, TenantStatus


@pytest.fixture
def building(db):
    return Building.objects.create(name="Preview Block", address="Nairobi")


def _tenant(building, label, idn, *, phone="254700000000", due_day=5):
    unit = Unit.objects.create(
        building=building, label=label, monthly_rent=Decimal("10000"),
        classification=UnitClassification.RESIDENTIAL, status=UnitStatus.OCCUPIED_UNPAID,
    )
    return Tenant.objects.create(
        first_name="T", last_name=idn, id_number=idn, phone=phone,
        unit=unit, monthly_rent=Decimal("10000"), due_day=due_day,
        move_in_date=dt.date(2026, 1, 1), status=TenantStatus.ACTIVE,
    )


def _arrear(tenant, balance):
    return Arrears.objects.create(
        tenant=tenant, period_month=9, period_year=2026,
        expected_rent=Decimal("10000"), expected_vat=Decimal("0"),
        amount_paid=Decimal("10000") - balance, balance=balance,
        is_cleared=balance <= 0,
    )


def _run(**kwargs):
    out = StringIO()
    call_command("preview_reminders", stdout=out, **kwargs)
    return out.getvalue()


class TestPreviewSendsNothing:
    def test_it_sends_no_sms_and_writes_no_notification(self, building):
        tenant = _tenant(building, "A1", "PRV1")
        _arrear(tenant, Decimal("10000"))

        with patch("apps.payments.notifications.send_sms") as sms, \
             patch("apps.payments.notifications.send_email") as email:
            _run(date="2026-09-10")

        assert not sms.called
        assert not email.called
        assert TenantNotification.objects.count() == 0

    def test_it_does_not_touch_the_arrears_it_reads(self, building):
        tenant = _tenant(building, "A2", "PRV2")
        arrear = _arrear(tenant, Decimal("7500"))
        before = arrear.balance

        _run(date="2026-09-10")

        arrear.refresh_from_db()
        assert arrear.balance == before
        assert arrear.is_cleared is False


class TestPreviewCounts:
    def test_overdue_tenant_is_counted_once_the_due_day_has_passed(self, building):
        tenant = _tenant(building, "B1", "PRV3")
        _arrear(tenant, Decimal("6000"))

        out = _run(date="2026-09-10")

        assert "would send             : 1" in out
        assert "KES 6,000.00" in out

    def test_nobody_is_chased_before_their_due_day(self, building):
        tenant = _tenant(building, "B2", "PRV4")
        _arrear(tenant, Decimal("6000"))

        out = _run(date="2026-09-02")

        # Rent reminder yes (due the 5th, lead 3), arrears chase no.
        arrears_section = out.split("arrears-reminders")[1]
        assert "would send             : 0" in arrears_section

    def test_a_cleared_period_is_not_chased(self, building):
        tenant = _tenant(building, "B3", "PRV5")
        _arrear(tenant, Decimal("0"))

        out = _run(date="2026-09-10")

        assert "total quoted as owed   : KES 0.00" in out

    def test_a_tenant_with_no_phone_is_reported_as_unreachable(self, building):
        _tenant(building, "B4", "PRV6", phone="")

        out = _run(date="2026-09-10")

        assert "no phone number : 1" in out

    def test_an_already_notified_tenant_is_shown_as_deduped(self, building):
        tenant = _tenant(building, "B5", "PRV7")
        _arrear(tenant, Decimal("6000"))
        TenantNotification.objects.create(
            tenant=tenant, channel="sms", subject="x", body="y",
            template_key="rent_overdue", dedupe_key=f"rent_overdue:{tenant.id}:2026-09",
        )

        out = _run(date="2026-09-10")

        arrears_section = out.split("arrears-reminders")[1]
        assert "would send             : 0" in arrears_section
        assert "already sent this month: 1" in arrears_section
