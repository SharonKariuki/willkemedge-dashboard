"""
``clear_non_rent_balances`` takes a property off the rent roll and leaves it at nil.

Scenario on MVN01: rent of 50,000 raised for September and October with
20,000 paid in October (80,000 owed by the old books), and November already
raised on the 25 Oct run. The landlord says the villa is not charged rent.
"""
import datetime as _dt
import io
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.buildings.models import Building, Unit, UnitStatus
from apps.payments.management.commands.clear_non_rent_balances import SOURCE
from apps.payments.models import Arrears, OpeningBalance, Payment, PaymentSource, PaymentType
from apps.payments.monthly_ledger import current_balance
from apps.payments.tasks import billable_active_tenants
from apps.tenants.models import Tenant, TenantStatus

TODAY = _dt.date(2026, 11, 14)


@pytest.fixture
def villa(db):
    building = Building.objects.create(name="Wilkem Edge Villas - Mt View Nairobi", total_floors=1)
    unit = Unit.objects.create(
        building=building, label="MVN01", monthly_rent=Decimal("50000"),
        status=UnitStatus.OCCUPIED_UNPAID,
    )
    tenant = Tenant.objects.create(
        first_name="Daniel", last_name="Mugambi", id_number="TEST-MVN01",
        phone="+254700000001", unit=unit, monthly_rent=Decimal("50000"),
        deposit_paid=Decimal("0"), move_in_date=_dt.date(2026, 6, 1),
        status=TenantStatus.ACTIVE,
    )
    for month in (9, 10, 11):
        Arrears.objects.create(
            tenant=tenant, period_month=month, period_year=2026,
            expected_rent=Decimal("50000"), amount_paid=0, balance=Decimal("50000"),
        )
    Payment.objects.create(
        tenant=tenant, amount=Decimal("20000"), payment_date=_dt.date(2026, 10, 5),
        period_month=10, period_year=2026, source=PaymentSource.CASH, payment_type=PaymentType.RENT,
    )
    return tenant


def _run(*args):
    out = io.StringIO()
    call_command("clear_non_rent_balances", "--unit", "MVN01", *args, stdout=out)
    return out.getvalue()


def test_preview_changes_nothing(villa):
    before = current_balance(villa, today=TODAY)
    _run()
    villa.refresh_from_db()
    assert villa.is_billable is True
    assert not OpeningBalance.objects.filter(tenant=villa).exists()
    assert Arrears.objects.filter(tenant=villa).count() == 3
    assert current_balance(villa, today=TODAY) == before


def test_apply_stops_rent_and_leaves_nil(villa):
    output = _run("--apply")
    villa.refresh_from_db()

    assert villa.is_billable is False
    assert villa.monthly_rent == Decimal("0")
    assert villa not in billable_active_tenants()

    ob = OpeningBalance.objects.get(tenant=villa)
    assert (ob.as_of, ob.amount, ob.source) == (_dt.date(2026, 10, 31), Decimal("0"), SOURCE)

    # November's rent is gone; September and October stay on file, outside the books.
    assert sorted(Arrears.objects.filter(tenant=villa).values_list("period_month", flat=True)) == [9, 10]
    assert current_balance(villa, today=TODAY) == Decimal("0")
    assert "Applied." in output


def test_rerun_is_a_no_op(villa):
    _run("--apply")
    _run("--apply")
    assert OpeningBalance.objects.filter(tenant=villa).count() == 1
    assert current_balance(villa, today=TODAY) == Decimal("0")


def test_paid_rent_in_the_books_is_refused(villa):
    Arrears.objects.filter(tenant=villa, period_month=11).update(amount_paid=Decimal("5000"))
    with pytest.raises(CommandError, match="nothing was saved"):
        _run("--apply")
    villa.refresh_from_db()
    assert villa.is_billable is True
    assert not OpeningBalance.objects.filter(tenant=villa).exists()


def test_undo_restores_the_history(villa):
    _run("--apply")
    _run("--undo", "--apply")
    assert not OpeningBalance.objects.filter(tenant=villa).exists()
    # Rent stays off; the old September/October balance counts again.
    villa.refresh_from_db()
    assert villa.is_billable is False
    assert current_balance(villa, today=TODAY) == Decimal("80000")


def test_unknown_unit_is_rejected(db):
    with pytest.raises(CommandError, match="Not a non-rent unit"):
        call_command("clear_non_rent_balances", "--unit", "MR302", stdout=io.StringIO())
