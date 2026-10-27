"""One bank credit split into deposit + rent.

A new tenant usually pays the deposit and the first month's rent in one
transfer. Booked whole as rent, the deposit became an overpayment and the books
held no deposit at all (MR203: 53,000 as October rent; DON2A: a 20,000 deposit
as October rent). Assign now books the deposit part first — by default the
deposit the tenant's card says is still to come, for a letting with no rent
received yet — and the director can set the split by hand.
"""
import datetime as dt
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.buildings.models import Building, Unit, UnitStatus
from apps.payments.models import Arrears, CoopIpnEvent, CoopIpnStatus, Payment, PaymentType
from apps.payments.services import allocate_payment_fifo
from apps.tenants.deposits import default_deposit_part, deposit_held_on_books
from apps.tenants.models import Tenant, TenantStatus

User = get_user_model()
URL = "/api/unmatched-credits/"


@pytest.fixture
def owner(db):
    user = User.objects.create_user(username="osoro", email="o@t.com", password="pw12345678!", role="owner")
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _tenant(label="MR203", rent="27000", card_deposit="25000", move_in=dt.date(2026, 5, 31),
            first_rent_month=dt.date(2026, 6, 1)):
    building, _ = Building.objects.get_or_create(name="Matasia Residential", defaults={"total_floors": 3})
    unit = Unit.objects.create(
        building=building, label=label, monthly_rent=Decimal(rent), status=UnitStatus.OCCUPIED_UNPAID,
    )
    return Tenant.objects.create(
        first_name="Samuel", last_name=label, id_number=f"ID-{label}", phone="+254700000001",
        unit=unit, monthly_rent=Decimal(rent), deposit_paid=Decimal(card_deposit),
        move_in_date=move_in, first_rent_month=first_rent_month, status=TenantStatus.ACTIVE,
    )


def _event(trans_id, amount, posting="2026-05-15"):
    return CoopIpnEvent.objects.create(
        transaction_id=trans_id, amount=Decimal(amount), event_type="CREDIT",
        narration="UF7HG6UZBO~90290#~254700000001~MPESAC2B_400222~SAMUEL",
        raw_payload={"PostingDate": posting, "Amount": amount},
        status=CoopIpnStatus.UNMATCHED, detail="No tenant match",
    )


def _live(tenant, payment_type):
    return sum(
        (p.amount for p in Payment.objects.filter(
            tenant=tenant, payment_type=payment_type, voided_at__isnull=True)),
        Decimal("0"),
    )


# --- allocator -----------------------------------------------------------

@pytest.mark.django_db
def test_deposit_part_is_booked_as_deposit_and_the_rest_as_rent():
    tenant = _tenant()

    payments = allocate_payment_fifo(
        tenant=tenant, amount=Decimal("53000"), payment_date=dt.date(2026, 5, 15),
        source="mpesa", reference="CB1", idempotency_key="CB1", deposit_amount=Decimal("28000"),
    )

    assert [(p.payment_type, p.amount) for p in payments] == [
        (PaymentType.DEPOSIT, Decimal("28000")), (PaymentType.RENT, Decimal("25000")),
    ]
    assert [p.idempotency_key for p in payments] == ["CB1#0", "CB1#1"]
    # The rent is June's, the first rent month; the deposit settles no rent.
    june = Arrears.objects.get(tenant=tenant)
    assert (june.period_year, june.period_month) == (2026, 6)
    assert june.balance == Decimal("2000")


@pytest.mark.django_db
def test_replaying_a_split_credit_books_nothing_new():
    tenant = _tenant()
    kwargs = dict(
        tenant=tenant, amount=Decimal("53000"), payment_date=dt.date(2026, 5, 15),
        source="mpesa", reference="CB1", idempotency_key="CB1", deposit_amount=Decimal("28000"),
    )
    first = allocate_payment_fifo(**kwargs)

    again = allocate_payment_fifo(**kwargs)

    assert [p.pk for p in again] == [p.pk for p in first]
    assert Payment.objects.filter(tenant=tenant).count() == 2


@pytest.mark.django_db
def test_a_deposit_part_larger_than_the_credit_is_refused():
    tenant = _tenant()

    with pytest.raises(ValueError):
        allocate_payment_fifo(
            tenant=tenant, amount=Decimal("1000"), payment_date=dt.date(2026, 5, 15),
            deposit_amount=Decimal("2000"),
        )


# --- the default -----------------------------------------------------------

@pytest.mark.django_db
def test_default_is_the_card_deposit_still_to_come_for_a_new_letting():
    tenant = _tenant(card_deposit="25000")

    assert default_deposit_part(tenant, Decimal("53000")) == Decimal("25000")
    assert default_deposit_part(tenant, Decimal("10000")) == Decimal("10000")


@pytest.mark.django_db
def test_default_is_nothing_once_rent_has_been_received():
    tenant = _tenant(card_deposit="25000")
    allocate_payment_fifo(tenant=tenant, amount=Decimal("27000"), payment_date=dt.date(2026, 6, 3))

    assert default_deposit_part(tenant, Decimal("53000")) == Decimal("0")


@pytest.mark.django_db
def test_default_never_reaches_past_the_card_to_the_one_month_rule():
    """A tenant with no deposit declared keeps every shilling as rent."""
    tenant = _tenant(card_deposit="0")

    assert default_deposit_part(tenant, Decimal("53000")) == Decimal("0")


@pytest.mark.django_db
def test_default_is_nothing_when_the_deposit_was_already_booked_in_cash():
    tenant = _tenant(card_deposit="25000")
    allocate_payment_fifo(
        tenant=tenant, amount=Decimal("25000"), payment_date=dt.date(2026, 5, 15),
        payment_type=PaymentType.DEPOSIT,
    )

    assert default_deposit_part(tenant, Decimal("27000")) == Decimal("0")


# --- reconciliation assign -------------------------------------------------

@pytest.mark.django_db
@patch("apps.payments.tasks.send_deposit_receipt.delay")
def test_assign_splits_by_default(_receipt, owner):
    tenant = _tenant(card_deposit="25000")
    event = _event("CB0403388", "25000")

    resp = owner.post(f"{URL}{event.id}/assign/", {"tenant": tenant.id}, format="json")

    assert resp.status_code == 200, resp.content
    assert _live(tenant, PaymentType.DEPOSIT) == Decimal("25000")
    assert _live(tenant, PaymentType.RENT) == Decimal("0")
    assert not Arrears.objects.filter(tenant=tenant).exists()


@pytest.mark.django_db
@patch("apps.payments.tasks.send_deposit_receipt.delay")
def test_director_can_split_by_hand_and_the_card_follows(_receipt, owner):
    tenant = _tenant(card_deposit="25000")
    event = _event("CB0385042", "27000", posting="2026-05-23")

    resp = owner.post(
        f"{URL}{event.id}/assign/", {"tenant": tenant.id, "deposit_amount": "28000"}, format="json",
    )
    assert resp.status_code == 400  # more than the credit

    resp = owner.post(
        f"{URL}{event.id}/assign/", {"tenant": tenant.id, "deposit_amount": "3000"}, format="json",
    )

    assert resp.status_code == 200, resp.content
    assert _live(tenant, PaymentType.DEPOSIT) == Decimal("3000")
    assert _live(tenant, PaymentType.RENT) == Decimal("24000")
    tenant.refresh_from_db()
    assert deposit_held_on_books(tenant) == Decimal("3000")


@pytest.mark.django_db
@patch("apps.payments.tasks.send_deposit_receipt.delay")
def test_director_can_book_it_all_as_rent(_receipt, owner):
    tenant = _tenant(card_deposit="25000")
    event = _event("CB9", "27000")

    resp = owner.post(
        f"{URL}{event.id}/assign/", {"tenant": tenant.id, "deposit_amount": "0"}, format="json",
    )

    assert resp.status_code == 200
    assert _live(tenant, PaymentType.DEPOSIT) == Decimal("0")
    assert _live(tenant, PaymentType.RENT) == Decimal("27000")


@pytest.mark.django_db
@patch("apps.payments.tasks.send_deposit_receipt.delay")
def test_split_preview(_receipt, owner):
    tenant = _tenant(card_deposit="25000")
    event = _event("CB10", "53000")

    resp = owner.get(f"{URL}{event.id}/split/", {"tenant": tenant.id})

    assert resp.status_code == 200
    assert resp.json() == {
        "amount": "53000.00", "deposit_amount": "25000.00", "rent_amount": "28000.00",
        "deposit_still_to_receive": "25000.00",
    }


@pytest.mark.django_db
@patch("apps.payments.tasks.send_deposit_receipt.delay")
def test_mr203_end_to_end(_receipt, owner):
    """Deposit 25,000 + S/C and water 3,000, then November rent: 53,000 in three credits."""
    tenant = _tenant(card_deposit="25000")
    for trans_id, amount, posting, deposit in (
        ("CB0403388", "25000", "2026-05-15", None),   # default: the 25,000 on the card
        ("CB0385042", "27000", "2026-05-23", "3000"),  # S/C + water deposit by hand
        ("CB0387303", "1000", "2026-05-23", None),     # rent now received: all rent
    ):
        body = {"tenant": tenant.id}
        if deposit is not None:
            body["deposit_amount"] = deposit
        event = _event(trans_id, amount, posting)
        assert owner.post(f"{URL}{event.id}/assign/", body, format="json").status_code == 200

    assert _live(tenant, PaymentType.DEPOSIT) == Decimal("28000")
    june = Arrears.objects.get(tenant=tenant)
    assert (june.period_year, june.period_month, june.amount_paid, june.balance) == (
        2026, 6, Decimal("25000"), Decimal("2000"),
    )
    tenant.refresh_from_db()
    assert tenant.deposit_paid == Decimal("28000")
