"""
Tests for M-Pesa Daraja webhook endpoints.

Covers:
  - validate: accepts valid unit+tenant, rejects unknown bill ref
  - validate: accepts duplicate TransID silently (replay protection)
  - validate: rejects zero/negative amount
  - confirm: records payment correctly
  - confirm: idempotent on duplicate TransID (no double payment)
  - confirm: accepts even when tenant unmatched (so Safaricom stops retrying)
  - confirm: dispatches send_payment_confirmation task
"""
from decimal import Decimal
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from apps.buildings.models import Building, Unit, UnitStatus
from apps.payments.models import Payment, PaymentSource
from apps.tenants.models import Tenant, TenantStatus


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def building(db):
    return Building.objects.create(name="Test Block", total_floors=3)


@pytest.fixture
def unit(building):
    return Unit.objects.create(
        building=building, label="A1", monthly_rent=Decimal("15000"),
        status=UnitStatus.OCCUPIED_UNPAID,
    )


@pytest.fixture
def tenant(unit):
    return Tenant.objects.create(
        first_name="Jane", last_name="Wanjiku", id_number="12345678",
        phone="+254712345678", unit=unit,
        monthly_rent=Decimal("15000"), move_in_date="2026-01-01",
        status=TenantStatus.ACTIVE,
    )

VALIDATE_URL = "/api/payments/mpesa/validate/"
CONFIRM_URL  = "/api/payments/mpesa/confirm/"


def mpesa_payload(bill_ref="A1", amount="15000", trans_id="MPE123ABC"):
    return {
        "TransID": trans_id, "BillRefNumber": bill_ref,
        "TransAmount": amount, "MSISDN": "254712345678",
        "TransTime": "20260413120000",
    }


# ── Validate ────────────────────────────────────────────────────────────────

class TestMpesaValidate:
    def test_accepts_valid_unit_with_active_tenant(self, client, tenant):
        resp = client.post(VALIDATE_URL, mpesa_payload(), format="json")
        assert resp.status_code == 200
        assert resp.data["ResultCode"] == 0

    def test_rejects_unknown_bill_ref(self, client, db):
        resp = client.post(VALIDATE_URL, mpesa_payload(bill_ref="ZZZ"), format="json")
        assert resp.status_code == 200
        assert resp.data["ResultCode"] == 1

    def test_rejects_zero_amount(self, client, tenant):
        resp = client.post(VALIDATE_URL, mpesa_payload(amount="0"), format="json")
        assert resp.status_code == 200
        assert resp.data["ResultCode"] == 1

    def test_rejects_negative_amount(self, client, tenant):
        resp = client.post(VALIDATE_URL, mpesa_payload(amount="-100"), format="json")
        assert resp.status_code == 200
        assert resp.data["ResultCode"] == 1

    def test_accepts_duplicate_trans_id_silently(self, client, tenant):
        """Replay: TransID already in DB → accept without re-processing."""
        Payment.objects.create(
            tenant=tenant, amount=Decimal("15000"),
            payment_date="2026-04-13", period_month=4, period_year=2026,
            source=PaymentSource.MPESA, reference="MPE123ABC",
        )
        resp = client.post(VALIDATE_URL, mpesa_payload(trans_id="MPE123ABC"), format="json")
        assert resp.status_code == 200
        assert resp.data["ResultCode"] == 0  # Accept, don't reject

    def test_rejects_unit_with_no_active_tenant(self, client, unit):
        """Unit exists but has no ACTIVE tenant."""
        resp = client.post(VALIDATE_URL, mpesa_payload(), format="json")
        assert resp.status_code == 200
        assert resp.data["ResultCode"] == 1


# ── Confirm ─────────────────────────────────────────────────────────────────

class TestMpesaConfirm:
    @patch("apps.payments.views_mpesa.send_payment_confirmation.delay")
    def test_records_payment_and_fires_task(self, mock_task, client, tenant):
        resp = client.post(CONFIRM_URL, mpesa_payload(), format="json")
        assert resp.status_code == 200
        assert resp.data["ResultCode"] == 0
        assert Payment.objects.filter(reference="MPE123ABC").exists()
        mock_task.assert_called_once()

    @patch("apps.payments.views_mpesa.send_payment_confirmation.delay")
    def test_idempotent_on_duplicate_trans_id(self, mock_task, client, tenant):
        """Second call with same TransID must NOT create a second payment."""
        client.post(CONFIRM_URL, mpesa_payload(), format="json")
        client.post(CONFIRM_URL, mpesa_payload(), format="json")
        assert Payment.objects.filter(reference="MPE123ABC").count() == 1
        mock_task.assert_called_once()

    def test_returns_200_even_for_unmatched_tenant(self, client, db):
        """Safaricom must receive 200 even if we can't match the tenant."""
        resp = client.post(CONFIRM_URL, mpesa_payload(bill_ref="UNKNOWN"), format="json")
        assert resp.status_code == 200
        assert resp.data["ResultCode"] == 0

    @patch("apps.payments.views_mpesa.send_payment_confirmation.delay")
    def test_full_payment_sets_unit_to_paid(self, _mock, client, tenant):
        client.post(CONFIRM_URL, mpesa_payload(amount="15000"), format="json")
        tenant.unit.refresh_from_db()
        assert tenant.unit.status == UnitStatus.OCCUPIED_PAID

    @patch("apps.payments.views_mpesa.send_payment_confirmation.delay")
    def test_partial_payment_sets_unit_to_partial(self, _mock, client, tenant):
        client.post(CONFIRM_URL, mpesa_payload(amount="8000"), format="json")
        tenant.unit.refresh_from_db()
        assert tenant.unit.status == UnitStatus.OCCUPIED_PARTIAL
