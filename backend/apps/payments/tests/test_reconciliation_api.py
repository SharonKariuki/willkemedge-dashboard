"""
Tests for the manual reconciliation API (Day 4 · Feature 6B).

  - list returns only UNMATCHED Co-op credits (auth required)
  - assign books the payment, marks the event RECORDED, drops it from the queue
  - assigning a non-unmatched event → 409; unknown tenant → 404
"""
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.buildings.models import Building, Unit, UnitStatus
from apps.payments.models import CoopIpnEvent, CoopIpnStatus, Payment
from apps.tenants.models import Tenant, TenantStatus

User = get_user_model()
LIST_URL = "/api/unmatched-credits/"


@pytest.fixture
def auth_client(db):
    user = User.objects.create_user(username="admin", email="a@t.com", password="pw12345678!", role="owner")
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def tenant(db):
    building = Building.objects.create(name="Road Block", total_floors=4)
    unit = Unit.objects.create(
        building=building, label="RB001", monthly_rent=Decimal("20000"),
        status=UnitStatus.OCCUPIED_UNPAID,
    )
    return Tenant.objects.create(
        first_name="Sarah", last_name="Hamisi", id_number="T1", phone="+254726012481",
        unit=unit, monthly_rent=Decimal("20000"), move_in_date="2026-01-01",
        status=TenantStatus.ACTIVE,
    )


def _event(trans_id="CB1", status=CoopIpnStatus.UNMATCHED, amount="20000"):
    return CoopIpnEvent.objects.create(
        transaction_id=trans_id, amount=Decimal(amount), event_type="CREDIT",
        narration="UF7HG6UZBO~90290#~254726012481~MPESAC2B_400222~SARAH HAMISI",
        raw_payload={"PostingDate": "2026-05-27", "Amount": amount},
        status=status, detail="No tenant match",
    )


class TestReconciliationApi:
    def test_requires_auth(self, db):
        assert APIClient().get(LIST_URL).status_code == 401

    def test_list_returns_only_unmatched(self, auth_client):
        _event("CB1", status=CoopIpnStatus.UNMATCHED)
        _event("CB2", status=CoopIpnStatus.RECORDED)
        _event("CB3", status=CoopIpnStatus.IGNORED)
        resp = auth_client.get(LIST_URL)
        assert resp.status_code == 200
        ids = [e["transaction_id"] for e in resp.json()]
        assert ids == ["CB1"]
        assert resp.json()[0]["payer_hint"]["phone"] == "254726012481"

    @patch("apps.payments.tasks.send_deposit_receipt.delay")
    def test_assign_books_payment_and_records_event(self, mock_receipt, auth_client, tenant):
        event = _event("CB_ASSIGN")
        resp = auth_client.post(f"{LIST_URL}{event.id}/assign/", {"tenant": tenant.id}, format="json")
        assert resp.status_code == 200
        event.refresh_from_db()
        assert event.status == CoopIpnStatus.RECORDED
        assert event.payment_id is not None
        payment = Payment.objects.get(reference="CB_ASSIGN")
        assert payment.tenant_id == tenant.id
        assert payment.amount == Decimal("20000")
        mock_receipt.assert_called_once()
        # It drops out of the unmatched queue.
        assert auth_client.get(LIST_URL).json() == []

    def test_assign_non_unmatched_event_conflicts(self, auth_client, tenant):
        event = _event("CB_DONE", status=CoopIpnStatus.RECORDED)
        resp = auth_client.post(f"{LIST_URL}{event.id}/assign/", {"tenant": tenant.id}, format="json")
        assert resp.status_code == 409
        assert Payment.objects.count() == 0

    def test_assign_unknown_tenant_404(self, auth_client):
        event = _event("CB_NOTENANT")
        resp = auth_client.post(f"{LIST_URL}{event.id}/assign/", {"tenant": 99999}, format="json")
        assert resp.status_code == 404

    def test_assign_requires_tenant_field(self, auth_client):
        event = _event("CB_NOFIELD")
        resp = auth_client.post(f"{LIST_URL}{event.id}/assign/", {}, format="json")
        assert resp.status_code == 400
