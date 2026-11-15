"""One cheque, several tenancies.

Sidai pays for its Healthcare tenancy (MCG05 + MCG06) and its Office & Physio
tenancy (MCG08 + MCG09) with one cheque. ``POST /api/payments/split/`` books
one payment per tenancy, all or nothing, and the parts stay one payment: they
must add up to the cheque, and voiding any part voids them all.
"""
import datetime as dt
from decimal import Decimal
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.payments.models import Payment, Transaction
from apps.tenants.models import Tenant, TenantStatus

User = get_user_model()
PAY_DATE = dt.date(2026, 11, 10)
URL = "/api/payments/split/"


@pytest.fixture
def coa(db):
    call_command("seed_coa")


@pytest.fixture
def sidai(db):
    building = Building.objects.create(name="Matasia Commercial", address="Matasia")

    def tenancy(label, name, rent):
        unit = Unit.objects.create(
            building=building, label=label, monthly_rent=Decimal(rent),
            classification=UnitClassification.BUSINESS, status=UnitStatus.OCCUPIED_UNPAID,
        )
        return Tenant.objects.create(
            first_name="Sidai", last_name=name, id_number=f"TEST-{label}", phone="254700000000",
            unit=unit, monthly_rent=Decimal(rent), move_in_date=dt.date(2026, 1, 1),
            status=TenantStatus.ACTIVE,
        )

    return tenancy("MCG05", "Healthcare", "106500"), tenancy("MCG08", "Office & Physio", "70655")


@pytest.fixture
def api(db):
    user = User.objects.create_user(
        username="owner", email="owner@test.com", password="Str0ngPassw0rd!x", role=Role.OWNER,
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _body(health, office, *, total="205500.00", a="123540.00", b="81960.00", ref="CHQ004512"):
    return {
        "amount": total,
        "payment_date": PAY_DATE.isoformat(),
        "source": "cheque",
        "reference": ref,
        "parts": [
            {"tenant": health.pk, "amount": a, "period_month": 11, "period_year": 2026},
            {"tenant": office.pk, "amount": b, "period_month": 11, "period_year": 2026},
        ],
    }


@pytest.fixture(autouse=True)
def receipts():
    with mock.patch("apps.payments.views.send_payment_confirmation") as task:
        yield task


def test_books_one_payment_per_tenancy(api, sidai, coa, django_capture_on_commit_callbacks, receipts):
    health, office = sidai
    with django_capture_on_commit_callbacks(execute=True):
        resp = api.post(URL, _body(health, office), format="json")
    assert resp.status_code == 201, resp.data

    parts = list(Payment.objects.order_by("split_index"))
    assert [(p.tenant_id, p.amount) for p in parts] == [
        (health.pk, Decimal("123540.00")), (office.pk, Decimal("81960.00")),
    ]
    assert len({p.split_group for p in parts}) == 1 and parts[0].split_group
    assert [(p.split_index, p.split_count, p.split_total) for p in parts] == [
        (1, 2, Decimal("205500.00")), (2, 2, Decimal("205500.00")),
    ]
    assert all(p.reference == "CHQ004512" for p in parts)
    assert "Part 1 of 2 of CHQ004512" in parts[0].notes
    # Each part is an ordinary payment: its own Transaction (VAT split out) ...
    assert Transaction.objects.filter(payment__in=parts).count() == 2
    # ... and its own receipt, sent once the whole split is saved.
    assert sorted(c.args[0] for c in receipts.delay.call_args_list) == [p.pk for p in parts]


@pytest.mark.parametrize("a,b", [("100000.00", "81960.00"), ("123540.00", "90000.00")])
def test_parts_must_add_up_to_the_cheque(api, sidai, coa, a, b):
    health, office = sidai
    resp = api.post(URL, _body(health, office, a=a, b=b), format="json")
    assert resp.status_code == 400
    assert "must match exactly" in str(resp.data["parts"])
    assert not Payment.objects.exists()


def test_a_split_needs_two_parts(api, sidai, coa):
    health, office = sidai
    body = _body(health, office, total="123540.00")
    body["parts"] = body["parts"][:1]
    resp = api.post(URL, body, format="json")
    assert resp.status_code == 400
    assert not Payment.objects.exists()


def test_one_bad_part_books_nothing(api, sidai, coa):
    health, office = sidai
    body = _body(health, office)
    body["parts"][1]["period_month"] = 13
    resp = api.post(URL, body, format="json")
    assert resp.status_code == 400
    assert not Payment.objects.exists()


def test_double_submit_books_once(api, sidai, coa):
    health, office = sidai
    assert api.post(URL, _body(health, office), format="json").status_code == 201
    assert api.post(URL, _body(health, office), format="json").status_code == 201
    assert Payment.objects.count() == 2


def test_voiding_one_part_voids_the_whole_cheque(api, sidai, coa):
    health, office = sidai
    api.post(URL, _body(health, office), format="json")
    first, second = Payment.objects.order_by("split_index")

    preview = api.get(f"/api/payments/{second.pk}/void-preview/").data
    assert [s["id"] for s in preview["siblings"]] == [first.pk]
    assert preview["total"] == "205500.00"

    resp = api.post(f"/api/payments/{second.pk}/void/", {"reason": "wrong split"}, format="json")
    assert resp.status_code == 200, resp.data
    assert resp.data["voided_count"] == 2
    assert not Payment.objects.filter(voided_at__isnull=True).exists()


def test_a_part_cannot_be_voided_alone(api, sidai, coa):
    health, office = sidai
    api.post(URL, _body(health, office), format="json")
    part = Payment.objects.first()
    resp = api.post(f"/api/payments/{part.pk}/void/", {"reason": "x", "scope": "single"}, format="json")
    assert resp.status_code == 400
    assert not Payment.objects.filter(voided_at__isnull=False).exists()


def test_same_cheque_number_on_ordinary_payments_still_groups_per_tenant(api, sidai, coa):
    """A split doesn't change how un-split payments that share a reference void."""
    health, office = sidai
    for tenant in (health, office):
        api.post("/api/payments/", {
            "tenant": tenant.pk, "amount": "1000.00", "payment_date": PAY_DATE.isoformat(),
            "period_month": 11, "period_year": 2026, "source": "cheque", "reference": "CHQ1",
        }, format="json")
    first = Payment.objects.get(tenant=health)
    api.post(f"/api/payments/{first.pk}/void/", {"reason": "x"}, format="json")
    assert Payment.objects.get(tenant=office).voided_at is None
