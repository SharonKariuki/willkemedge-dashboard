"""
Two guard rails added after the permissions review.

  * Django's admin site is the superadmin's alone: it has its own permission
    system, outside the access rules the API enforces.
  * When someone voids, cancels or deletes an entry they made themselves, the
    activity log says so. Nothing is blocked - there is one director, so a
    second approver is not always there - but the director can see it.
"""
import datetime as _dt
from decimal import Decimal

import pytest

from apps.accounts import audit
from apps.accounts.models import AuditLog, User
from apps.buildings.models import Building, Unit, UnitStatus
from apps.payments.models import Payment, PaymentSource, PaymentType
from apps.tenants.models import Tenant, TenantStatus


def _user(email, **extra):
    return User.objects.create_user(username=email, email=email, password="pw-123456!", **extra)


# --- Django admin -----------------------------------------------------------


@pytest.mark.django_db
def test_admin_site_is_closed_to_staff_who_are_not_the_superadmin(client):
    staff = _user("staff@wilkem.test", is_staff=True, role="owner")
    client.force_login(staff)
    response = client.get("/admin/")
    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


@pytest.mark.django_db
def test_admin_site_opens_for_the_superadmin(client):
    boss = User.objects.create_superuser(
        username="root@wilkem.test", email="root@wilkem.test", password="pw-123456!"
    )
    client.force_login(boss)
    assert client.get("/admin/").status_code == 200


# --- Undoing your own entry -------------------------------------------------


@pytest.fixture
def tenant(db):
    building = Building.objects.create(name="Test Court", total_floors=1)
    unit = Unit.objects.create(
        building=building, label="TC01", monthly_rent=Decimal("9000"),
        status=UnitStatus.OCCUPIED_UNPAID,
    )
    return Tenant.objects.create(
        first_name="Test", last_name="Tenant", id_number="TEST-TC01",
        phone="+254700000001", unit=unit, monthly_rent=Decimal("9000"),
        deposit_paid=Decimal("0"), move_in_date=_dt.date(2026, 6, 1),
        status=TenantStatus.ACTIVE,
    )


def _payment(tenant, maker):
    return Payment.objects.create(
        tenant=tenant, amount=Decimal("9000"), payment_date=_dt.date(2026, 9, 5),
        source=PaymentSource.CASH, payment_type=PaymentType.RENT,
        period_month=9, period_year=2026, created_by=maker,
    )


def _void(payment, actor):
    return audit.record(
        action="payment.void", object_type="payment", object_id=payment.pk,
        summary="Voided payment", actor=actor,
    )


@pytest.mark.django_db
def test_voiding_your_own_payment_is_flagged(tenant):
    clerk = _user("clerk@wilkem.test", role="accountant")
    row = _void(_payment(tenant, clerk), clerk)
    assert row.new_values["self_reversal"] is True
    assert row.summary.endswith("(their own entry)")


@pytest.mark.django_db
def test_voiding_someone_elses_payment_is_not_flagged(tenant):
    clerk = _user("clerk@wilkem.test", role="accountant")
    owner = _user("owner@wilkem.test", role="owner")
    row = _void(_payment(tenant, clerk), owner)
    assert "self_reversal" not in row.new_values
    assert row.summary == "Voided payment"


@pytest.mark.django_db
def test_an_entry_with_no_maker_is_not_flagged(tenant):
    owner = _user("owner@wilkem.test", role="owner")
    row = _void(_payment(tenant, None), owner)
    assert "self_reversal" not in row.new_values


@pytest.mark.django_db
def test_deleting_your_own_expense_is_flagged_from_its_create_row():
    clerk = _user("clerk@wilkem.test", role="accountant")
    audit.record(
        kind="change", action="expense.create", object_type="expense", object_id=41,
        summary="Created expense", actor=clerk,
    )
    row = audit.record(
        kind="change", action="expense.delete", object_type="expense", object_id=41,
        summary="Deleted expense", actor=clerk,
    )
    assert row.new_values == {"self_reversal": True}


@pytest.mark.django_db
def test_other_actions_on_your_own_entry_are_not_flagged(tenant):
    clerk = _user("clerk@wilkem.test", role="accountant")
    payment = _payment(tenant, clerk)
    row = audit.record(
        action="payment.receipt_sent", object_type="payment", object_id=payment.pk,
        summary="Sent receipt", actor=clerk,
    )
    assert "self_reversal" not in row.new_values
    assert AuditLog.objects.count() >= 1
