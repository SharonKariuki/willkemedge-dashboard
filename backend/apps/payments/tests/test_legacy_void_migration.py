"""The 0017 migration must convert old negative "VOID:" payments.

Databases that used the previous reversal flow hold an equal-and-opposite
Payment with a negative amount. Those rows never posted to the ledger for
commercial tenants and mis-posted deposits, so they are migrated onto the void
flag instead.
"""
import datetime as dt
import importlib
from contextlib import contextmanager
from decimal import Decimal

import pytest
from django.apps import apps as django_apps
from django.db import connection

from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.payments.models import Arrears, Payment, PaymentType
from apps.tenants.models import Tenant, TenantStatus


def _convert():
    return importlib.import_module(
        "apps.payments.migrations.0017_convert_legacy_void_payments"
    ).convert


@contextmanager
def _without_payment_amount_check():
    """Run with `payment_amount_positive` lifted.

    This test seeds the state of a database BEFORE this release: a legacy
    reversal written as an equal-and-opposite Payment with a NEGATIVE amount.
    That shape is exactly what the constraint now forbids, and forbidding it is
    the point — but it did not exist when those rows were written, and 0017 runs
    long before 0021 installs it, so the migration legitimately has to cope with
    data the current schema would reject.

    Lifting the constraint for the duration is therefore modelling reality, not
    working around the check. `convert()` deletes the negative rows, so the data
    satisfies the constraint again by the time it is restored — which is itself
    a useful assertion: if the migration left a negative row behind, restoring
    the constraint here would fail.

    NB: `schema_editor.remove_constraint` does NOT work here. On SQLite Django
    implements it by rebuilding the table from the model's `_meta`, which still
    declares the constraint — so it is silently re-created. The backend-specific
    routes below are the ones that actually take effect.
    """
    table = Payment._meta.db_table
    name = "payment_amount_positive"
    vendor = connection.vendor

    with connection.cursor() as cursor:
        if vendor == "sqlite":
            cursor.execute("PRAGMA ignore_check_constraints = ON")
        else:
            cursor.execute(f'ALTER TABLE "{table}" DROP CONSTRAINT IF EXISTS "{name}"')
    try:
        yield
    finally:
        with connection.cursor() as cursor:
            if vendor == "sqlite":
                cursor.execute("PRAGMA ignore_check_constraints = OFF")
            else:
                # Re-adding validates the surviving rows, so this doubles as an
                # assertion that `convert()` left no negative payment behind.
                cursor.execute(
                    f'ALTER TABLE "{table}" ADD CONSTRAINT "{name}" CHECK (amount > 0)'
                )


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


@pytest.mark.django_db(transaction=True)
def test_legacy_void_pair_becomes_a_void_flag(tenant):
    original = Payment.objects.create(
        tenant=tenant, amount=Decimal("10000"), payment_date=dt.date(2026, 6, 5),
        period_month=6, period_year=2026, payment_type=PaymentType.RENT,
        reference="MPESA123",
    )
    Arrears.objects.create(
        tenant=tenant, period_month=6, period_year=2026,
        expected_rent=Decimal("10000"), expected_vat=Decimal("0"),
        amount_paid=Decimal("0"), balance=Decimal("10000"), is_cleared=False,
    )

    with _without_payment_amount_check():
        Payment.objects.create(
            tenant=tenant, amount=Decimal("-10000"), payment_date=dt.date(2026, 6, 5),
            period_month=6, period_year=2026, reference="VOID:MPESA123",
            notes="Reversal authorized; voids payment #1",
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
