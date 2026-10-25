"""repair_first_rent_month on MR203 as it stood on 25 Oct 2026."""
import datetime as dt
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from apps.buildings.models import Building, Unit, UnitStatus
from apps.payments.models import Arrears, CoopIpnEvent, CoopIpnStatus, Payment, PaymentType
from apps.payments.services import assign_unmatched_credit
from apps.tenants.deposits import deposit_held_on_books
from apps.tenants.models import Tenant, TenantStatus

CREDITS = (
    ("CB0403388_15102026_2", "25000", "2026-10-15"),
    ("CB0385042_23102026_2", "27000", "2026-10-23"),
    ("CB0387303_23102026_2", "1000", "2026-10-23"),
)


@pytest.fixture
def mr203(db):
    """All 53,000 booked as October rent against an October charge."""
    building = Building.objects.create(name="Matasia Residential", total_floors=3)
    unit = Unit.objects.create(
        building=building, label="MR203", monthly_rent=Decimal("27000"),
        status=UnitStatus.OCCUPIED_UNPAID,
    )
    tenant = Tenant.objects.create(
        first_name="Samuel", last_name="Mogoko", id_number="ID-MR203", phone="+254700000002",
        unit=unit, monthly_rent=Decimal("27000"), deposit_paid=Decimal("25000"),
        move_in_date=dt.date(2026, 10, 31), status=TenantStatus.ACTIVE,
    )
    for trans_id, amount, posting in CREDITS:
        event = CoopIpnEvent.objects.create(
            transaction_id=trans_id, amount=Decimal(amount), event_type="CREDIT",
            narration="X~90290#MR203~254700000002~MPESAC2B_400222~SAMUEL",
            raw_payload={"PostingDate": posting, "Amount": amount},
            status=CoopIpnStatus.UNMATCHED,
        )
        # How it was booked before the split existed: all rent.
        assign_unmatched_credit(event_id=event.pk, tenant=tenant, deposit_amount=Decimal("0"))
    return tenant


def _run(*args):
    out = StringIO()
    call_command("repair_first_rent_month", "--unit", "MR203", *args, stdout=out)
    return out.getvalue()


def _state(tenant):
    return (
        sorted(Arrears.objects.filter(tenant=tenant).values_list("period_year", "period_month")),
        deposit_held_on_books(tenant),
    )


def test_the_fixture_reproduces_the_fault(mr203):
    assert _state(mr203) == ([(2026, 10)], Decimal("0"))


def test_preview_changes_nothing(mr203):
    before = _state(mr203)

    output = _run()

    assert "PREVIEW" in output
    mr203.refresh_from_db()
    assert _state(mr203) == before
    assert mr203.first_rent_month is None


def test_apply_rebooks_deposit_and_november(mr203):
    _run("--apply")

    mr203.refresh_from_db()
    assert mr203.first_rent_month == dt.date(2026, 11, 1)
    assert _state(mr203) == ([(2026, 11)], Decimal("28000"))
    november = Arrears.objects.get(tenant=mr203)
    assert (november.amount_paid, november.balance) == (Decimal("25000"), Decimal("2000"))
    assert mr203.deposit_paid == Decimal("28000")
    # Every credit is booked again, nothing is left in the queue.
    assert not CoopIpnEvent.objects.filter(status=CoopIpnStatus.UNMATCHED).exists()
    assert Payment.objects.filter(
        tenant=mr203, payment_type=PaymentType.DEPOSIT, voided_at__isnull=True,
    ).count() == 2
