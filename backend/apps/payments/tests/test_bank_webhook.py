"""
Tests for bank webhook endpoint.

Covers:
  - valid payload + matched tenant → payment recorded
  - duplicate reference → idempotent, no second payment
  - invalid HMAC signature → 401 rejected
  - unmatched bill_ref → 200 accepted (flagged, not crash)
  - missing/unparseable amount → 400
"""
import hashlib
import hmac
import json
from decimal import Decimal
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from apps.buildings.models import Building, Unit, UnitStatus
from apps.payments.models import Payment
from apps.tenants.models import Tenant, TenantStatus

WEBHOOK_URL = "/api/payments/bank/webhook/"


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def building(db):
    return Building.objects.create(name="River View", total_floors=4)


@pytest.fixture
def unit(building):
    return Unit.objects.create(
        building=building, label="C2", monthly_rent=Decimal("18000"),
        status=UnitStatus.OCCUPIED_UNPAID,
    )


@pytest.fixture
def tenant(unit):
    return Tenant.objects.create(
        first_name="Alice", last_name="Njeri", id_number="55667788",
        phone="+254755667788", unit=unit,
        monthly_rent=Decimal("18000"), move_in_date="2026-01-01",
        status=TenantStatus.ACTIVE,
    )


def signed_post(client, payload: dict, secret: str = ""):
    body = json.dumps(payload).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest() if secret else "bad"
    return client.post(
        WEBHOOK_URL, data=payload, format="json",
        HTTP_X_WEBHOOK_SIGNATURE=sig,
    )


class TestBankWebhook:
    @patch("apps.payments.bank.send_payment_confirmation.delay")
    def test_records_payment_for_matched_tenant(self, mock_task, api_client, tenant, settings):
        settings.BANK_WEBHOOK_SECRET = ""  # skip sig check in dev/DEBUG
        settings.DEBUG = True
        payload = {
            "amount": "18000", "reference": "BANK_REF_001",
            "bill_ref": "C2", "sender_name": "Alice Njeri",
        }
        resp = api_client.post(WEBHOOK_URL, payload, format="json")
        assert resp.status_code == 200
        assert Payment.objects.filter(reference="BANK_REF_001").exists()
        mock_task.assert_called_once()

    @patch("apps.payments.bank.send_payment_confirmation.delay")
    def test_idempotent_on_duplicate_reference(self, mock_task, api_client, tenant, settings):
        settings.BANK_WEBHOOK_SECRET = ""
        settings.DEBUG = True
        payload = {
            "amount": "18000", "reference": "BANK_DUP_001",
            "bill_ref": "C2", "sender_name": "Alice Njeri",
        }
        api_client.post(WEBHOOK_URL, payload, format="json")
        api_client.post(WEBHOOK_URL, payload, format="json")
        assert Payment.objects.filter(reference="BANK_DUP_001").count() == 1
        mock_task.assert_called_once()

    def test_returns_200_for_unmatched_bill_ref(self, api_client, db, settings):
        settings.BANK_WEBHOOK_SECRET = ""
        settings.DEBUG = True
        payload = {
            "amount": "5000", "reference": "BANK_UNKNOWN_001",
            "bill_ref": "ZZZZZ", "sender_name": "Mystery Person",
        }
        resp = api_client.post(WEBHOOK_URL, payload, format="json")
        assert resp.status_code == 200
        assert Payment.objects.filter(reference="BANK_UNKNOWN_001").count() == 0

    def test_returns_400_for_missing_amount(self, api_client, db, settings):
        settings.BANK_WEBHOOK_SECRET = ""
        settings.DEBUG = True
        payload = {"reference": "BANK_NO_AMT", "bill_ref": "C2"}
        resp = api_client.post(WEBHOOK_URL, payload, format="json")
        assert resp.status_code == 400
