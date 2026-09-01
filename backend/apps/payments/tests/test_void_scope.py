"""How much a void unwinds.

One bank credit routinely becomes several Payment rows — FIFO allocation
splits it across the periods it settles. The dashboard's void button therefore
has to unwind the whole credit by default, or the money the user thinks they
removed is still sitting on the tenant's account. These tests pin that, and
pin the two things the grouping must never do: reach across tenants, or group
manual entries that merely share a blank reference.
"""
import datetime as dt
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.payments.models import Payment
from apps.payments.services import process_payment
from apps.tenants.models import Tenant, TenantStatus

User = get_user_model()
PAY_DATE = dt.date(2026, 6, 5)


@pytest.fixture
def coa(db):
    call_command("seed_coa")


@pytest.fixture
def building(db):
    return Building.objects.create(name="Void Block", address="Nairobi")


def _tenant(building, label, idn):
    unit = Unit.objects.create(
        building=building, label=label, monthly_rent=Decimal("10000"),
        classification=UnitClassification.RESIDENTIAL, status=UnitStatus.OCCUPIED_UNPAID,
    )
    return Tenant.objects.create(
        first_name="T", last_name=idn, id_number=idn, phone="254700000000",
        unit=unit, monthly_rent=Decimal("10000"), move_in_date=dt.date(2026, 1, 1),
        status=TenantStatus.ACTIVE,
    )


def _owner_client():
    user = User.objects.create_user(
        username="owner", email="owner@test.com",
        password="Str0ngPassw0rd!x", role=Role.OWNER,
    )
    api = APIClient()
    api.force_authenticate(user=user)
    return api


def _split_credit(tenant, ref, periods):
    """Book one bank credit as several rows, the way FIFO allocation leaves it."""
    return [
        process_payment(
            tenant=tenant, amount=Decimal("5000"), payment_date=PAY_DATE,
            period_month=month, period_year=2026, reference=ref,
            idempotency_key=f"{ref}#{month}",
        )
        for month in periods
    ]


class TestVoidScope:
    def test_reference_scope_voids_every_chunk_of_one_credit(self, building, coa):
        api = _owner_client()
        t = _tenant(building, "V1", "VS1")
        chunks = _split_credit(t, "MPESA1", [5, 6])

        resp = api.post(
            f"/api/payments/{chunks[0].pk}/void/",
            {"reason": "paid to the wrong unit"}, format="json",
        )

        assert resp.status_code == 200
        assert resp.json()["voided_count"] == 2
        assert not Payment.objects.filter(
            reference="MPESA1", voided_at__isnull=True
        ).exists()

    def test_default_scope_is_reference(self, building, coa):
        """No scope in the body means the whole credit — the safe reading."""
        api = _owner_client()
        t = _tenant(building, "V2", "VS2")
        chunks = _split_credit(t, "MPESA2", [5, 6])

        api.post(f"/api/payments/{chunks[0].pk}/void/", {"reason": "x"}, format="json")

        assert Payment.objects.filter(
            reference="MPESA2", voided_at__isnull=True
        ).count() == 0

    def test_single_scope_leaves_the_other_legs_alone(self, building, coa):
        api = _owner_client()
        t = _tenant(building, "V3", "VS3")
        chunks = _split_credit(t, "MPESA3", [5, 6])

        resp = api.post(
            f"/api/payments/{chunks[0].pk}/void/",
            {"reason": "wrong period", "scope": "single"}, format="json",
        )

        assert resp.json()["voided_count"] == 1
        live = Payment.objects.filter(reference="MPESA3", voided_at__isnull=True)
        assert [p.pk for p in live] == [chunks[1].pk]

    def test_grouping_never_reaches_across_tenants(self, building, coa):
        """Two tenants sharing a receipt-book number stay separate (C1)."""
        api = _owner_client()
        t1 = _tenant(building, "V4", "VS4")
        t2 = _tenant(building, "V5", "VS5")
        mine = process_payment(
            tenant=t1, amount=Decimal("10000"), payment_date=PAY_DATE,
            period_month=6, period_year=2026, reference="007", idempotency_key="007a",
        )
        theirs = process_payment(
            tenant=t2, amount=Decimal("10000"), payment_date=PAY_DATE,
            period_month=6, period_year=2026, reference="007", idempotency_key="007b",
        )

        api.post(f"/api/payments/{mine.pk}/void/", {"reason": "x"}, format="json")

        theirs.refresh_from_db()
        assert theirs.voided_at is None

    def test_blank_reference_groups_nothing(self, building, coa):
        """Manual cash entries share no key, so each must stand alone."""
        api = _owner_client()
        t = _tenant(building, "V6", "VS6")
        first = process_payment(
            tenant=t, amount=Decimal("4000"), payment_date=PAY_DATE,
            period_month=5, period_year=2026, reference="", idempotency_key="k1",
        )
        second = process_payment(
            tenant=t, amount=Decimal("4000"), payment_date=PAY_DATE,
            period_month=6, period_year=2026, reference="", idempotency_key="k2",
        )

        resp = api.post(f"/api/payments/{first.pk}/void/", {"reason": "x"}, format="json")

        assert resp.json()["voided_count"] == 1
        second.refresh_from_db()
        assert second.voided_at is None

    def test_unknown_scope_is_rejected(self, building, coa):
        api = _owner_client()
        t = _tenant(building, "V7", "VS7")
        p = _split_credit(t, "MPESA7", [6])[0]

        resp = api.post(
            f"/api/payments/{p.pk}/void/",
            {"reason": "x", "scope": "everything"}, format="json",
        )

        assert resp.status_code == 400
        p.refresh_from_db()
        assert p.voided_at is None


class TestVoidPreview:
    def test_preview_lists_the_whole_credit_without_voiding_it(self, building, coa):
        api = _owner_client()
        t = _tenant(building, "P1", "VP1")
        chunks = _split_credit(t, "MPESA8", [5, 6])

        body = api.get(f"/api/payments/{chunks[0].pk}/void-preview/").json()

        assert body["payment"]["id"] == chunks[0].pk
        assert [s["id"] for s in body["siblings"]] == [chunks[1].pk]
        assert Decimal(body["total"]) == Decimal("10000.00")
        assert Payment.objects.filter(
            reference="MPESA8", voided_at__isnull=True
        ).count() == 2

    def test_preview_of_a_standalone_payment_has_no_siblings(self, building, coa):
        api = _owner_client()
        t = _tenant(building, "P2", "VP2")
        p = _split_credit(t, "MPESA9", [6])[0]

        body = api.get(f"/api/payments/{p.pk}/void-preview/").json()

        assert body["siblings"] == []
        assert Decimal(body["total"]) == Decimal("5000.00")
