"""
Tests for the Sidai reconciliation (MCG05 + MCG06 space, MCF12).

The fixture is the production shape as found on 17 Oct 2026: one 161,480 credit
assigned to MCG05 alone in two FIFO chunks (98,080 July, 63,400 September),
and MCF12's September charged but unpaid. The acceptance test is that the
credit ends as the 16 Sept sheet reads it — 102,720 on MCG05, 58,760 on MCF12 —
with the July chunk untouched and nothing invented or lost.
"""
import datetime as _dt
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.payments.management.commands import reconcile_sidai_matasia as cmd
from apps.payments.models import Arrears, Payment
from apps.tenants.models import Tenant, TenantStatus

D = Decimal
REF = cmd.REF


def _tenant(building, label, rent, id_number, status=TenantStatus.ACTIVE):
    unit = Unit.objects.create(
        building=building, label=label, monthly_rent=rent,
        classification=UnitClassification.BUSINESS, status=UnitStatus.OCCUPIED_UNPAID,
    )
    return Tenant.objects.create(
        first_name="Sidai", last_name=label, id_number=id_number,
        phone="+254722301981", unit=unit, monthly_rent=rent,
        move_in_date="2026-07-21", status=status,
    )


def _charge(tenant, month, rent, vat):
    Arrears.objects.create(
        tenant=tenant, period_year=2026, period_month=month,
        expected_rent=rent, expected_vat=vat, amount_paid=D(0),
        balance=rent + vat, is_cleared=False,
    )


@pytest.fixture
def sidai(db, monkeypatch):
    """MCG05 and MCF12 as production held them on 17 Oct 2026."""
    from apps.payments.services import process_payment

    building = Building.objects.create(name="Matasia Arcade", code="MCR", total_floors=2)
    mcg05 = _tenant(building, "MCG05", D("86500"), "S-MCG05")
    mcf12 = _tenant(building, "MCF12", D("50655"), "S-MCF12", TenantStatus.NOTICE_GIVEN)
    monkeypatch.setattr(cmd, "MCG05", ("MCG05", mcg05.pk, "MCG05"))
    monkeypatch.setattr(cmd, "MCF12", ("MCF12", mcf12.pk, "MCF12"))
    monkeypatch.setattr(cmd, "TENANCIES", (cmd.MCG05, cmd.MCF12))

    Unit.objects.create(
        building=building, label="MCG06", monthly_rent=D("15000"),
        classification=UnitClassification.BUSINESS, status=UnitStatus.VACANT,
    )
    for month in (7, 9, 10):
        _charge(mcg05, month, D("86500"), D("13840"))
    _charge(mcf12, 9, D("50655"), D("8104.80"))

    for i, (amount, month) in enumerate(((D("98080"), 7), (D("63400"), 9))):
        process_payment(
            tenant=mcg05, amount=amount, payment_date=_dt.date(2026, 9, 14),
            period_month=month, period_year=2026, source="bank",
            reference=REF, idempotency_key=f"{REF}#{i}",
        )
    return mcg05, mcf12


def _shape(tenant):
    return sorted(
        (p.amount, p.period_month)
        for p in Payment.objects.filter(tenant=tenant, reference=REF, voided_at__isnull=True)
    )


def test_the_split_adds_up_to_the_credit():
    assert sum((a for _k, a, _p in cmd.TARGET), D(0)) == cmd.BANKED


def test_dry_run_writes_nothing(sidai):
    mcg05, mcf12 = sidai
    call_command("reconcile_sidai_matasia")

    assert _shape(mcg05) == [(D("63400.00"), 9), (D("98080.00"), 7)]
    assert _shape(mcf12) == []


def test_apply_splits_the_credit_as_the_sheet_reads_it(sidai):
    mcg05, mcf12 = sidai
    july_chunk = Payment.objects.get(tenant=mcg05, reference=REF, period_month=7)

    call_command("reconcile_sidai_matasia", "--apply")

    assert _shape(mcg05) == [(D("4640.00"), 9), (D("98080.00"), 7)]
    assert _shape(mcf12) == [(D("58760.00"), 9)]
    assert Payment.objects.filter(pk=july_chunk.pk, voided_at__isnull=True).exists(), (
        "the July chunk is not this command's to move"
    )

    sep = Arrears.objects.get(tenant=mcf12, period_year=2026, period_month=9)
    assert sep.expected_vat == D("8105.00")
    assert sep.balance == D("0.00")


def test_mcg06_joins_mcg05s_space_at_the_combined_rent(sidai):
    mcg05, _ = sidai
    call_command("reconcile_sidai_matasia", "--apply")

    mcg05.refresh_from_db()
    assert mcg05.monthly_rent == D("106500.00")
    assert Unit.objects.get(label="MCG06").combined_into_id == mcg05.unit_id


def test_october_is_charged_as_the_7_oct_sheet_bills_it(sidai):
    mcg05, mcf12 = sidai
    call_command("reconcile_sidai_matasia", "--apply")

    g05 = Arrears.objects.get(tenant=mcg05, period_year=2026, period_month=10)
    f12 = Arrears.objects.get(tenant=mcf12, period_year=2026, period_month=10)
    assert (g05.expected_rent, g05.expected_vat) == (D("106500.00"), D("17040.00"))
    assert (f12.expected_rent, f12.expected_vat) == (D("50655.00"), D("8105.00"))


def test_rerun_changes_nothing(sidai):
    call_command("reconcile_sidai_matasia", "--apply")
    count = Payment.objects.count()

    call_command("reconcile_sidai_matasia", "--apply")

    assert Payment.objects.count() == count


def test_refuses_when_the_credit_no_longer_totals_the_bank_amount(sidai):
    mcg05, _ = sidai
    from apps.payments.services import void_payment

    void_payment(Payment.objects.get(tenant=mcg05, reference=REF, period_month=9), reason="test")
    call_command("reconcile_sidai_matasia", "--apply")

    assert _shape(mcg05) == [(D("98080.00"), 7)], "a short credit must not be re-cut"


def test_aborts_when_an_id_is_on_another_unit(sidai, monkeypatch):
    mcg05, _ = sidai
    monkeypatch.setattr(cmd, "TENANCIES", (("MCG05", mcg05.pk, "MCG06"), cmd.MCF12))

    with pytest.raises(CommandError, match="Pre-flight failed"):
        call_command("reconcile_sidai_matasia", "--apply")
