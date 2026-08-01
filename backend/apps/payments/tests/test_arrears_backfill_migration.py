"""The 0016 data migration must correct arrears rows already in the database.

Fixing the code alone leaves every historical row on the old, wrong basis:
commercial periods cleared 16% early, and deposits counted as rent. This
exercises the migration's `recompute` against rows deliberately written in the
broken shape.
"""
import datetime as dt
from decimal import Decimal

import pytest
from django.apps import apps as django_apps

from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.payments.models import Arrears, Payment, PaymentType
from apps.tenants.models import Tenant, TenantStatus


def _load_recompute():
    """Import the migration module by path (its name starts with a digit)."""
    import importlib

    module = importlib.import_module(
        "apps.payments.migrations.0016_recompute_arrears_with_vat"
    )
    return module.recompute


@pytest.fixture
def building(db):
    return Building.objects.create(name="Backfill Block")


def _setup(building, label, rent, classification, idn):
    unit = Unit.objects.create(
        building=building, label=label, monthly_rent=rent,
        classification=classification, status=UnitStatus.OCCUPIED_UNPAID,
    )
    return Tenant.objects.create(
        first_name="T", last_name=idn, id_number=idn, phone="254700000000",
        unit=unit, monthly_rent=rent, move_in_date=dt.date(2026, 1, 1),
        status=TenantStatus.ACTIVE,
    )


@pytest.mark.django_db
def test_migration_corrects_commercial_and_deposit_rows(building):
    recompute = _load_recompute()

    commercial = _setup(building, "MC1", Decimal("24000"), UnitClassification.BUSINESS, "MIG1")
    residential = _setup(building, "MR1", Decimal("15000"), UnitClassification.RESIDENTIAL, "MIG2")

    # Commercial tenant paid the correct gross; the OLD code recorded the period
    # as cleared with a 3,840 "overpayment".
    Payment.objects.create(
        tenant=commercial, amount=Decimal("27840"), payment_date=dt.date(2026, 6, 5),
        period_month=6, period_year=2026, payment_type=PaymentType.RENT, reference="M1",
    )
    # Residential tenant paid only a deposit; the OLD code marked rent paid.
    Payment.objects.create(
        tenant=residential, amount=Decimal("15000"), payment_date=dt.date(2026, 6, 1),
        period_month=6, period_year=2026, payment_type=PaymentType.DEPOSIT, reference="M2",
    )

    # Arrears rows exactly as the pre-fix code would have left them.
    Arrears.objects.create(
        tenant=commercial, period_month=6, period_year=2026,
        expected_rent=Decimal("24000"), expected_vat=Decimal("0"),
        amount_paid=Decimal("27840"), balance=Decimal("0"), is_cleared=True,
    )
    Arrears.objects.create(
        tenant=residential, period_month=6, period_year=2026,
        expected_rent=Decimal("15000"), expected_vat=Decimal("0"),
        amount_paid=Decimal("15000"), balance=Decimal("0"), is_cleared=True,
    )

    recompute(django_apps, None)

    com = Arrears.objects.get(tenant=commercial, period_month=6)
    assert com.expected_vat == Decimal("3840.00")
    assert com.amount_paid == Decimal("27840.00")
    assert com.balance == Decimal("0.00")   # correct gross payment still clears
    assert com.is_cleared is True

    res = Arrears.objects.get(tenant=residential, period_month=6)
    assert res.amount_paid == Decimal("0.00")     # the deposit is not rent
    assert res.balance == Decimal("15000.00")
    assert res.is_cleared is False


@pytest.mark.django_db
def test_migration_reopens_a_commercial_period_paid_at_base_only(building):
    """A tenant who paid only the base rent must go back to owing the VAT."""
    recompute = _load_recompute()

    t = _setup(building, "MC2", Decimal("24000"), UnitClassification.BUSINESS, "MIG3")
    Payment.objects.create(
        tenant=t, amount=Decimal("24000"), payment_date=dt.date(2026, 6, 5),
        period_month=6, period_year=2026, payment_type=PaymentType.RENT, reference="M3",
    )
    Arrears.objects.create(
        tenant=t, period_month=6, period_year=2026,
        expected_rent=Decimal("24000"), expected_vat=Decimal("0"),
        amount_paid=Decimal("24000"), balance=Decimal("0"), is_cleared=True,
    )

    recompute(django_apps, None)

    ar = Arrears.objects.get(tenant=t, period_month=6)
    assert ar.balance == Decimal("3840.00")
    assert ar.is_cleared is False
