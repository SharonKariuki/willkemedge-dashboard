"""
Tests for the Co-op Bank IPN receiver.

Covers:
  - missing/invalid bearer token  → 401, nothing stored
  - CREDIT matched by bill ref     → Payment recorded, event=RECORDED, spec body
  - CREDIT matched by payer phone  → Payment recorded (phone fallback)
  - duplicate TransactionId        → idempotent, no second Payment
  - DEBIT / non-credit event       → 200, IGNORED, no Payment
  - unmatched credit               → 200, UNMATCHED queue, no Payment
  - missing TransactionId          → 400
  - response body matches spec     → {"MessageCode":"200", ...}
"""
from decimal import Decimal
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from apps.buildings.models import Building, Unit, UnitStatus
from apps.payments.models import Arrears, CoopIpnEvent, CoopIpnStatus, Payment
from apps.tenants.models import Tenant, TenantStatus

IPN_URL = "/api/payments/coop/ipn/"
TOKEN = "test-coop-token-123"


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture(autouse=True)
def _ipn_token(settings):
    """All tests run with a configured bearer token unless they override it."""
    settings.COOP_IPN_TOKEN = TOKEN
    settings.ALLOW_INSECURE_COOP_IPN = False


@pytest.fixture
def building(db):
    return Building.objects.create(name="River View", total_floors=4)


@pytest.fixture
def unit(building):
    return Unit.objects.create(
        building=building, label="A12", monthly_rent=Decimal("20000"),
        status=UnitStatus.OCCUPIED_UNPAID,
    )


@pytest.fixture
def tenant(unit):
    return Tenant.objects.create(
        first_name="Melvin", last_name="Wanjiku", id_number="11223344",
        phone="+254707919065", unit=unit,
        monthly_rent=Decimal("20000"), move_in_date="2026-01-01",
        status=TenantStatus.ACTIVE,
    )


def _post(client, payload, token=TOKEN):
    headers = {}
    if token is not None:
        headers["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    return client.post(IPN_URL, payload, format="json", **headers)


def _credit(trans_id="CB0089060_1", amount="20000", narration=None, bill_ref="A12"):
    # Narration mirrors the spec's M-Pesa sample layout.
    if narration is None:
        narration = "TIP6V5IRAE~254707919065~01120000568900~MPESAC2B_400200~MELVIN WANJIKU"
    return {
        "AcctNo": "01136069098300",
        "Amount": amount,
        "Currency": "KES",
        "EventType": "CREDIT",
        "Narration": narration,
        "BillRefNumber": bill_ref,
        "PaymentRef": "25092025_409511749",
        "TransactionId": trans_id,
        "PostingDate": "2026-05-27",
    }


class TestCoopIpnAuth:
    def test_missing_token_rejected(self, api_client, db):
        resp = _post(api_client, _credit(), token=None)
        assert resp.status_code == 401
        assert CoopIpnEvent.objects.count() == 0

    def test_wrong_token_rejected(self, api_client, db):
        resp = _post(api_client, _credit(), token="nope")
        assert resp.status_code == 401
        assert CoopIpnEvent.objects.count() == 0


class TestCoopIpnProcessing:
    @patch("apps.payments.coop_ipn.send_deposit_receipt.delay")
    def test_credit_matched_by_bill_ref(self, mock_receipt, api_client, tenant):
        resp = _post(api_client, _credit(bill_ref="A12"))
        assert resp.status_code == 200
        assert resp.json() == {"MessageCode": "200", "Message": "Successfully received data"}
        assert Payment.objects.filter(reference="CB0089060_1").count() == 1
        event = CoopIpnEvent.objects.get(transaction_id="CB0089060_1")
        assert event.status == CoopIpnStatus.RECORDED
        assert event.payment is not None
        # one receipt for the full deposit
        mock_receipt.assert_called_once()
        assert mock_receipt.call_args.args[1] == "20000.00"  # total amount, quantized

    @patch("apps.payments.coop_ipn.send_deposit_receipt.delay")
    @patch("apps.payments.coop_ipn.send_unmatched_credit_alert.delay")
    def test_phone_only_match_is_queued_not_recorded(self, mock_alert, mock_receipt, api_client, tenant):
        # No usable bill ref; only the payer phone matches. Low confidence ⇒
        # queued for review, NOT auto-recorded, no receipt, admin alerted (H2/M1).
        narration = "TIP6V5IRAE~254707919065~01120000568900~MPESAC2B_400200~MELVIN WANJIKU"
        resp = _post(api_client, _credit(narration=narration, bill_ref="ZZZ"))
        assert resp.status_code == 200
        event = CoopIpnEvent.objects.get(transaction_id="CB0089060_1")
        assert event.status == CoopIpnStatus.UNMATCHED
        assert "Low-confidence" in event.detail
        assert Payment.objects.count() == 0
        mock_receipt.assert_not_called()
        mock_alert.assert_called_once()

    @patch("apps.payments.coop_ipn.send_deposit_receipt.delay")
    @patch("apps.payments.coop_ipn.send_unmatched_credit_alert.delay")
    def test_real_world_narration_format_extracts_phone_from_position_2(
        self, mock_alert, mock_receipt, api_client, tenant
    ):
        # Real production format observed from Co-op IPN: position 1 = bill ref,
        # position 2 = payer phone (positions 1 and 2 are SWAPPED vs the spec sample).
        # When the payer's bill ref is incomplete (e.g. "90290#" with no house number),
        # phone fallback should still kick in.
        narration = "UF7HG6UZBO~90290#~254707919065~MPESAC2B_400222~HUSSEIN HAMISI"
        resp = _post(api_client, _credit(trans_id="CB_REAL_1", narration=narration, bill_ref="90290#"))
        assert resp.status_code == 200
        event = CoopIpnEvent.objects.get(transaction_id="CB_REAL_1")
        # Bill ref "90290#" normalises to empty → no bill-ref match.
        # Phone at position 2 (254707919065) matches the fixture tenant.
        # Phone-only → low confidence → UNMATCHED queued for review (H2).
        assert event.status == CoopIpnStatus.UNMATCHED
        assert "Low-confidence" in event.detail
        assert Payment.objects.count() == 0
        mock_alert.assert_called_once()

    @patch("apps.payments.coop_ipn.send_deposit_receipt.delay")
    def test_real_world_narration_matches_when_billref_is_complete(
        self, mock_receipt, api_client, tenant
    ):
        # Same real-world layout but the payer typed a complete bill ref
        # ("90290#A12") — should match the tenant on unit A12 and be RECORDED.
        narration = "UF7HG6UZBO~90290#A12~254707919065~MPESAC2B_400222~HUSSEIN HAMISI"
        resp = _post(api_client, _credit(trans_id="CB_REAL_2", narration=narration, bill_ref="90290#A12"))
        assert resp.status_code == 200
        event = CoopIpnEvent.objects.get(transaction_id="CB_REAL_2")
        assert event.status == CoopIpnStatus.RECORDED
        assert Payment.objects.count() == 1
        mock_receipt.assert_called_once()

    @patch("apps.payments.coop_ipn.send_deposit_receipt.delay")
    def test_credit_booked_to_posting_date_period(self, mock_receipt, api_client, tenant):
        # PostingDate in a prior month must drive the payment period (review C2).
        payload = _credit(bill_ref="A12")
        payload["PostingDate"] = "2026-03-15"
        _post(api_client, payload)
        payment = Payment.objects.get(reference="CB0089060_1")
        assert (payment.period_month, payment.period_year) == (3, 2026)
        assert payment.payment_date.isoformat() == "2026-03-15"

    @patch("apps.payments.coop_ipn.send_deposit_receipt.delay")
    def test_arrears_first_allocation_splits_across_periods(self, mock_receipt, api_client, tenant):
        # Tenant owes an older month; a lump credit clears the oldest first,
        # remainder to current period (review: arrears-first allocation).
        Arrears.objects.create(
            tenant=tenant, period_month=3, period_year=2026,
            expected_rent=Decimal("20000"), amount_paid=Decimal("0"),
            balance=Decimal("20000"), is_cleared=False,
        )
        _post(api_client, _credit(amount="50000", bill_ref="A12"))
        pays = Payment.objects.filter(reference="CB0089060_1").order_by("period_month")
        # one chunk clears March (20000), remainder (30000) to current period
        assert pays.count() == 2
        march = pays.get(period_month=3, period_year=2026)
        assert march.amount == Decimal("20000")
        assert Arrears.objects.get(tenant=tenant, period_month=3, period_year=2026).is_cleared
        # still a single receipt for the full 50,000
        mock_receipt.assert_called_once()
        assert mock_receipt.call_args.args[1] == "50000.00"

    def test_credit_to_other_account_ignored(self, api_client, tenant, settings):
        # AcctNo guard (review C3): a credit to a different account is not booked.
        settings.COOP_ACCOUNT_NUMBER = "01136069098300"
        payload = _credit(trans_id="CB_OTHER_ACCT", bill_ref="A12")
        payload["AcctNo"] = "99999999999999"
        resp = _post(api_client, payload)
        assert resp.status_code == 200
        event = CoopIpnEvent.objects.get(transaction_id="CB_OTHER_ACCT")
        assert event.status == CoopIpnStatus.IGNORED
        assert Payment.objects.count() == 0

    def test_missing_event_type_not_treated_as_credit(self, api_client, tenant):
        # review C4: absent EventType must NOT be assumed income.
        payload = _credit(trans_id="CB_NO_TYPE", bill_ref="A12")
        del payload["EventType"]
        resp = _post(api_client, payload)
        assert resp.status_code == 200
        event = CoopIpnEvent.objects.get(transaction_id="CB_NO_TYPE")
        assert event.status == CoopIpnStatus.IGNORED
        assert Payment.objects.count() == 0

    def test_non_kes_currency_ignored(self, api_client, tenant):
        payload = _credit(trans_id="CB_FX_1", bill_ref="A12")
        payload["Currency"] = "USD"
        resp = _post(api_client, payload)
        assert resp.status_code == 200
        event = CoopIpnEvent.objects.get(transaction_id="CB_FX_1")
        assert event.status == CoopIpnStatus.IGNORED
        assert "Non-KES" in event.detail
        assert Payment.objects.count() == 0

    @patch("apps.payments.coop_ipn.send_deposit_receipt.delay")
    def test_amount_is_quantized_to_2dp(self, mock_receipt, api_client, tenant):
        # Bank could send odd precision (e.g. interest fragment); we must round
        # to 2dp before booking — otherwise DecimalField(decimal_places=2) raises.
        payload = _credit(trans_id="CB_DP_1", bill_ref="A12", amount="1234.567")
        resp = _post(api_client, payload)
        assert resp.status_code == 200
        event = CoopIpnEvent.objects.get(transaction_id="CB_DP_1")
        assert event.status == CoopIpnStatus.RECORDED
        assert event.amount == Decimal("1234.57")

    @patch("apps.payments.coop_ipn.send_deposit_receipt.delay")
    def test_idempotent_on_duplicate_transaction_id(self, mock_receipt, api_client, tenant):
        _post(api_client, _credit(trans_id="CB_DUP_1", bill_ref="A12"))
        _post(api_client, _credit(trans_id="CB_DUP_1", bill_ref="A12"))
        assert Payment.objects.filter(reference="CB_DUP_1").count() == 1
        assert CoopIpnEvent.objects.filter(transaction_id="CB_DUP_1").count() == 1
        mock_receipt.assert_called_once()

    def test_plain_debit_ignored(self, api_client, tenant):
        # A debit with no reversal marker / prior credit is just ignored.
        payload = _credit(trans_id="CB_DEBIT_1", narration="BANK CHARGE~LEDGER FEE")
        payload["EventType"] = "DEBIT"
        resp = _post(api_client, payload)
        assert resp.status_code == 200
        event = CoopIpnEvent.objects.get(transaction_id="CB_DEBIT_1")
        assert event.status == CoopIpnStatus.IGNORED
        assert Payment.objects.filter(reference="CB_DEBIT_1").count() == 0

    @patch("apps.payments.coop_ipn.send_reversal_authorization_alert.delay")
    def test_reversal_held_for_director_authorization(self, mock_alert, api_client, tenant):
        # A DEBIT flagged as a reversal is NOT auto-applied; director is alerted.
        payload = _credit(trans_id="CB_REV_1", narration="REVERSAL OF TIP6V5IRAE~254707919065")
        payload["EventType"] = "DEBIT"
        resp = _post(api_client, payload)
        assert resp.status_code == 200
        assert resp.json()["MessageCode"] == "200"
        event = CoopIpnEvent.objects.get(transaction_id="CB_REV_1")
        assert event.status == CoopIpnStatus.REVERSAL_PENDING
        assert Payment.objects.filter(reference="CB_REV_1").count() == 0
        mock_alert.assert_called_once()

    @patch("apps.payments.coop_ipn.send_unmatched_credit_alert.delay")
    def test_unmatched_credit_queued(self, mock_alert, api_client, db):
        # No tenant exists; phone + bill ref both miss.
        narration = "TIP6V5IRAE~254700000000~01120000568900~MPESAC2B_400200~STRANGER"
        resp = _post(api_client, _credit(trans_id="CB_UNMATCHED_1",
                                         narration=narration, bill_ref="ZZZ"))
        assert resp.status_code == 200
        assert resp.json()["MessageCode"] == "200"
        event = CoopIpnEvent.objects.get(transaction_id="CB_UNMATCHED_1")
        assert event.status == CoopIpnStatus.UNMATCHED
        assert Payment.objects.count() == 0
        mock_alert.assert_called_once()  # admin notified

    def test_missing_transaction_id_rejected(self, api_client, db):
        payload = _credit()
        del payload["TransactionId"]
        resp = _post(api_client, payload)
        assert resp.status_code == 400
        assert CoopIpnEvent.objects.count() == 0
