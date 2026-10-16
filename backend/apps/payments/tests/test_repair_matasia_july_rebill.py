"""
Restating the July the catch-up billing raised over a nil Matasia opening.

MCG03 is the worked example. The 21 Aug 2026 statement opens it at nil, yet
July was billed 18,000 + 2,880 on 12 Sept, and 18,120 of the 3 Oct receipt
was allocated to it — so October read as unpaid. After the repair July owes
nothing and that cash settles October instead, with no payment touched.
"""
import datetime as _dt
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.payments.management.commands import reconcile_matasia_commercial as commercial
from apps.payments.management.commands import reconcile_matasia_residential as residential
from apps.payments.models import Arrears, Payment
from apps.payments.monthly_ledger import OPENING_MARKER
from apps.payments.services import process_payment
from apps.tenants.models import Tenant, TenantStatus

D = Decimal


@pytest.fixture
def arcade(db):
    building = Building.objects.create(name="Matasia Arcade", code="MCR", total_floors=2)

    def let(label):
        unit = Unit.objects.create(
            building=building, label=label, monthly_rent=D("18000"),
            classification=UnitClassification.BUSINESS, status=UnitStatus.OCCUPIED_UNPAID,
        )
        return Tenant.objects.create(
            first_name=label, last_name="Ltd", id_number=f"T-{label}",
            phone="+254700000003", unit=unit, monthly_rent=D("18000"),
            move_in_date="2026-07-21", status=TenantStatus.ACTIVE,
        )

    return {"barber": let("MCR03"), "salon": let("MCR02"), "clinic": let("MCR05")}


def _nil(monkeypatch, *tenants):
    rows = [(t.unit.label, t.pk, D(0), D(18000), D(2880), D(0), "") for t in tenants]
    monkeypatch.setattr(commercial, "STATEMENT", rows)
    monkeypatch.setattr(residential, "STATEMENT", [])


def _billed(tenant, month):
    return Arrears.objects.create(
        tenant=tenant, period_year=2026, period_month=month,
        expected_rent=D("18000"), expected_vat=D("2880"),
        amount_paid=D(0), balance=D("20880"), is_cleared=False,
    )


def _pay(tenant, amount, when, month, ref):
    process_payment(
        tenant=tenant, amount=D(amount), payment_date=when,
        period_month=month, period_year=2026, source="bank",
        reference=ref, idempotency_key=ref,
    )


def _row(tenant, month):
    return Arrears.objects.get(tenant=tenant, period_year=2026, period_month=month)


@pytest.fixture
def barber(arcade):
    """MCG03's shape: July rebilled, October cash drawn into it."""
    t = arcade["barber"]
    _billed(t, 7)
    _billed(t, 10)
    _pay(t, "18120", _dt.date(2026, 10, 3), 7, "OCT-INTO-JULY")
    _pay(t, "2760", _dt.date(2026, 10, 3), 10, "OCT-INTO-OCT")
    return t


def test_july_becomes_the_nil_opening(barber, monkeypatch):
    _nil(monkeypatch, barber)

    call_command("repair_matasia_july_rebill", "--apply")

    jul = _row(barber, 7)
    assert (jul.expected_rent, jul.expected_vat, jul.balance) == (D("0.00"), D("0.00"), D("0.00"))
    assert OPENING_MARKER in jul.waive_notes


def test_cash_paid_into_july_settles_the_oldest_open_month(barber, monkeypatch):
    _nil(monkeypatch, barber)
    assert _row(barber, 10).balance == D("18120.00")

    call_command("repair_matasia_july_rebill", "--apply")

    october = _row(barber, 10)
    assert october.balance == D("0.00"), "October still reads unpaid after the repair"
    assert october.is_cleared


def test_no_payment_is_written_or_voided(barber, monkeypatch):
    _nil(monkeypatch, barber)
    before = list(Payment.objects.order_by("pk").values_list("pk", "amount", "voided_at"))

    call_command("repair_matasia_july_rebill", "--apply")

    assert list(Payment.objects.order_by("pk").values_list("pk", "amount", "voided_at")) == before


def test_an_unpaid_rebilled_july_simply_clears(arcade, monkeypatch):
    """MCG02's shape: July billed 26,100 and nothing paid into it."""
    salon = arcade["salon"]
    _billed(salon, 7)
    _nil(monkeypatch, salon)

    call_command("repair_matasia_july_rebill", "--apply")

    assert _row(salon, 7).balance == D("0.00")


def test_a_july_with_cash_dated_in_july_is_held(arcade, monkeypatch):
    """MCG05's shape: a receipt dated 15 July sits against the July charge."""
    clinic = arcade["clinic"]
    _billed(clinic, 7)
    _pay(clinic, "20880", _dt.date(2026, 7, 15), 7, "JULY-CASH")
    _nil(monkeypatch, clinic)

    call_command("repair_matasia_july_rebill", "--apply")

    assert _row(clinic, 7).expected_rent == D("18000.00"), "a July with real July cash was restated"


def test_dry_run_writes_nothing(barber, monkeypatch):
    _nil(monkeypatch, barber)

    call_command("repair_matasia_july_rebill")

    assert _row(barber, 7).expected_rent == D("18000.00")


def test_rerun_changes_nothing(barber, monkeypatch):
    _nil(monkeypatch, barber)
    call_command("repair_matasia_july_rebill", "--apply")
    snapshot = list(Arrears.objects.filter(tenant=barber).values_list("period_month", "balance", "credit_applied"))

    call_command("repair_matasia_july_rebill", "--apply")

    after = list(Arrears.objects.filter(tenant=barber).values_list("period_month", "balance", "credit_applied"))
    assert after == snapshot


def test_aborts_when_an_id_is_on_another_unit(arcade, monkeypatch):
    t = arcade["barber"]
    monkeypatch.setattr(commercial, "STATEMENT", [("MCR99", t.pk, D(0), D(18000), D(2880), D(0), "")])
    monkeypatch.setattr(residential, "STATEMENT", [])
    _billed(t, 7)

    with pytest.raises(CommandError, match="Pre-flight failed"):
        call_command("repair_matasia_july_rebill", "--apply")

    assert _row(t, 7).expected_rent == D("18000.00")
