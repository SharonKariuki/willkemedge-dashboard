"""The 0017 migration must convert old negative "VOID:" payments.

Databases that used the previous reversal flow hold an equal-and-opposite
Payment with a negative amount. Those rows never posted to the ledger for
commercial tenants and mis-posted deposits, so they are migrated onto the void
flag instead.
"""
import datetime as dt
import importlib
from decimal import Decimal

import pytest
from django.apps import apps as django_apps

from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.payments.models import Arrears, Payment, PaymentType
from apps.tenants.models import Tenant, TenantStatus


def _convert():
    return importlib.import_module(
        "apps.payments.migrations.0017_convert_legacy_void_payments"
    ).convert


@pytest.fixture
def tenant(db):
    building = Building.objects.create(name="Legacy Block")
    unit = Unit.objects.create(
        building=building, label="LG1", monthly_rent=Decimal("10000"),
        classification=UnitClassification.RESIDENTIAL, status=UnitStatus.OCCUPIED_UNPAID,
    )
    return Tenant.objects.create(
        first_name="T", last_name="Legacy", id_number="LEG1", phone="254700000000",
        unit=unit, monthly_rent=Decimal("10000"), move_in_date=dt.date(2026, 1, 1),
        status=TenantStatus.ACTIVE,
    )


@pytest.mark.django_db
def test_legacy_void_pair_becomes_a_void_flag(tenant):
    original = Payment.objects.create(
        tenant=tenant, amount=Decimal("10000"), payment_date=dt.date(2026, 6, 5),
        period_month=6, period_year=2026, payment_type=PaymentType.RENT,
        reference="MPESA123",
    )
    Payment.objects.create(
        tenant=tenant, amount=Decimal("-10000"), payment_date=dt.date(2026, 6, 5),
        period_month=6, period_year=2026, reference="VOID:MPESA123",
        notes="Reversal authorized; voids payment #1",
    )
    Arrears.objects.create(
        tenant=tenant, period_month=6, period_year=2026,
        expected_rent=Decimal("10000"), expected_vat=Decimal("0"),
        amount_paid=Decimal("0"), balance=Decimal("10000"), is_cleared=False,
    )

    _convert()(django_apps, None)

    original.refresh_from_db()
    assert original.voided_at is not None
    assert "Reversal authorized" in original.void_reason
    # The negative row is gone.
    assert Payment.objects.filter(amount__lt=0).count() == 0
    # Arrears re-derived: the void means nothing was paid.
    ar = Arrears.objects.get(tenant=tenant, period_month=6)
    assert ar.amount_paid == Decimal("0.00")
    assert ar.balance == Decimal("10000.00")


@pytest.mark.django_db
def test_migration_is_a_no_op_without_legacy_rows(tenant):
    Payment.objects.create(
        tenant=tenant, amount=Decimal("10000"), payment_date=dt.date(2026, 6, 5),
        period_month=6, period_year=2026, payment_type=PaymentType.RENT, reference="CLEAN",
    )
    _convert()(django_apps, None)

    assert Payment.objects.count() == 1
    assert Payment.objects.get().voided_at is None
