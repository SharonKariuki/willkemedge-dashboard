"""Voiding a bank credit back into the reconciliation queue.

A credit booked to the wrong tenant or unit used to leave the books when it
was voided, and came back only if someone remembered to re-record it by hand.
`requeue` voids the whole credit and returns it to the queue in one step.
These tests pin that, the cases that must refuse (manual entries, a credit
that is only partly still booked, a single leg), and the replay-guard trap: the
void rows keep their `<txn>#<n>` keys, so re-assigning to the same tenant must
book fresh rows rather than hand back the void ones.
"""
import datetime as dt
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.accounts.models import AuditLog, Role
from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.payments.models import CoopIpnEvent, CoopIpnStatus, Payment
from apps.payments.services import assign_unmatched_credit, process_payment
from apps.tenants.models import Tenant, TenantStatus

User = get_user_model()
PAY_DATE = dt.date(2026, 6, 5)
QUEUE_URL = "/api/unmatched-credits/"


@pytest.fixture
def coa(db):
    call_command("seed_coa")


@pytest.fixture
def building(db):
    return Building.objects.create(name="Requeue Block", address="Nairobi")


@pytest.fixture
def owner(db):
    return User.objects.create_user(
        username="owner", email="owner@test.com",
        password="Str0ngPassw0rd!x", role=Role.OWNER,
    )


@pytest.fixture
def api(owner):
    client = APIClient()
    client.force_authenticate(user=owner)
    return client


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


def _unmatched(txn, amount="10000"):
    return CoopIpnEvent.objects.create(
        transaction_id=txn, amount=Decimal(amount), event_type="CREDIT",
        narration="UF7HG6UZBO~90290#B12~254700000000~MPESAC2B_400222~T WRONG",
        raw_payload={"PostingDate": PAY_DATE.isoformat(), "Amount": amount},
        status=CoopIpnStatus.UNMATCHED, detail="No tenant match",
    )


def _booked_credit(tenant, txn, amount="10000", owner=None):
    """A bank credit booked to `tenant` the way the queue's assign leaves it."""
    event, payments = assign_unmatched_credit(
        event_id=_unmatched(txn, amount).pk, tenant=tenant, actor=owner
    )
    return event, payments


def _split_credit(tenant, txn, periods):
    """One RECORDED credit split across several periods, as FIFO leaves it."""
    rows = [
        process_payment(
            tenant=tenant, amount=Decimal("5000"), payment_date=PAY_DATE,
            period_month=month, period_year=2026, reference=txn,
            idempotency_key=f"{txn}#{n}",
        )
        for n, month in enumerate(periods)
    ]
    event = _unmatched(txn, str(5000 * len(periods)))
    event.status = CoopIpnStatus.RECORDED
    event.payment = rows[0]
    event.save()
    return event, rows


def _void(api, payment, **body):
    return api.post(
        f"/api/payments/{payment.pk}/void/",
        {"reason": "paid to the wrong unit", **body}, format="json",
    )


class TestVoidAndRequeue:
    def test_requeue_voids_the_credit_and_returns_it_to_the_queue(self, api, building, coa, owner):
        wrong = _tenant(building, "A1", "RQ1")
        event, payments = _booked_credit(wrong, "CBQ1", owner=owner)

        resp = _void(api, payments[0], requeue=True)

        assert resp.status_code == 200, resp.content
        assert resp.json()["requeued_credit"] == event.pk
        assert Payment.objects.get(pk=payments[0].pk).voided_at is not None
        event.refresh_from_db()
        assert event.status == CoopIpnStatus.UNMATCHED
        assert event.payment_id is None
        assert event.void_requeue_count == 1
        assert "paid to the wrong unit" in event.detail

        queue = api.get(QUEUE_URL).json()
        assert [c["transaction_id"] for c in queue] == ["CBQ1"]
        assert queue[0]["void_requeue_count"] == 1
        assert AuditLog.objects.filter(action="credit.requeue", object_id=event.pk).exists()

    def test_requeue_unwinds_every_leg_of_a_split_credit(self, api, building, coa):
        wrong = _tenant(building, "A2", "RQ2")
        event, rows = _split_credit(wrong, "CBQ2", [5, 6])

        resp = _void(api, rows[1], requeue=True)

        assert resp.status_code == 200, resp.content
        assert resp.json()["voided_count"] == 2
        assert not Payment.objects.filter(reference="CBQ2", voided_at__isnull=True).exists()
        event.refresh_from_db()
        assert event.status == CoopIpnStatus.UNMATCHED

    @patch("apps.payments.tasks.send_deposit_receipt.delay")
    def test_reassign_to_another_tenant_books_it_there(self, _receipt, api, building, coa, owner):
        wrong = _tenant(building, "A3", "RQ3")
        right = _tenant(building, "B3", "RQ4")
        event, payments = _booked_credit(wrong, "CBQ3", owner=owner)
        _void(api, payments[0], requeue=True)

        resp = api.post(f"{QUEUE_URL}{event.pk}/assign/", {"tenant": right.pk}, format="json")

        assert resp.status_code == 200, resp.content
        live = Payment.objects.filter(reference="CBQ3", voided_at__isnull=True)
        assert [p.tenant_id for p in live] == [right.pk]
        assert sum(p.amount for p in live) == Decimal("10000")
        event.refresh_from_db()
        assert event.status == CoopIpnStatus.RECORDED
        assert event.payment.tenant_id == right.pk

    @patch("apps.payments.tasks.send_deposit_receipt.delay")
    def test_reassign_to_the_same_tenant_books_fresh_rows(self, _receipt, api, building, coa, owner):
        # The trap: the void rows still carry `CBQ5#0`. Re-booking under the
        # bare transaction id would return them and record nothing.
        tenant = _tenant(building, "A5", "RQ5")
        event, payments = _booked_credit(tenant, "CBQ5", owner=owner)
        _void(api, payments[0], requeue=True)

        resp = api.post(f"{QUEUE_URL}{event.pk}/assign/", {"tenant": tenant.pk}, format="json")

        assert resp.status_code == 200, resp.content
        live = list(Payment.objects.filter(reference="CBQ5", voided_at__isnull=True))
        assert len(live) == 1
        assert live[0].pk != payments[0].pk
        assert live[0].idempotency_key == "CBQ5~r1#0"
        event.refresh_from_db()
        assert event.payment_id == live[0].pk

    @patch("apps.payments.tasks.send_deposit_receipt.delay")
    def test_a_credit_can_be_requeued_more_than_once(self, _receipt, api, building, coa, owner):
        first = _tenant(building, "A6", "RQ6")
        second = _tenant(building, "B6", "RQ7")
        event, payments = _booked_credit(first, "CBQ6", owner=owner)
        _void(api, payments[0], requeue=True)
        api.post(f"{QUEUE_URL}{event.pk}/assign/", {"tenant": second.pk}, format="json")
        event.refresh_from_db()

        assert _void(api, event.payment, requeue=True).status_code == 200
        api.post(f"{QUEUE_URL}{event.pk}/assign/", {"tenant": first.pk}, format="json")

        live = list(Payment.objects.filter(reference="CBQ6", voided_at__isnull=True))
        assert [(p.tenant_id, p.idempotency_key) for p in live] == [(first.pk, "CBQ6~r2#0")]


class TestRequeueRefuses:
    def test_manual_entry_cannot_be_requeued(self, api, building, coa):
        t = _tenant(building, "C1", "RF1")
        p = process_payment(
            tenant=t, amount=Decimal("10000"), payment_date=PAY_DATE,
            period_month=6, period_year=2026, reference="",
        )

        preview = api.get(f"/api/payments/{p.pk}/void-preview/").json()
        assert preview["requeueable"] is False
        assert "bank feed" in preview["requeue_blocker"]

        resp = _void(api, p, requeue=True)
        assert resp.status_code == 409
        assert Payment.objects.get(pk=p.pk).voided_at is None

    def test_reference_that_only_shares_a_bank_id_is_not_requeueable(self, api, building, coa, owner):
        # A hand-entered payment quoting a transaction id that was booked to
        # someone else is not that credit's booking.
        owner_of_credit = _tenant(building, "C2", "RF2")
        other = _tenant(building, "C3", "RF3")
        _booked_credit(owner_of_credit, "CBR2", owner=owner)
        manual = process_payment(
            tenant=other, amount=Decimal("10000"), payment_date=PAY_DATE,
            period_month=6, period_year=2026, reference="CBR2",
        )

        assert _void(api, manual, requeue=True).status_code == 409
        assert Payment.objects.get(pk=manual.pk).voided_at is None

    def test_partly_voided_credit_cannot_go_back_whole(self, api, building, coa):
        t = _tenant(building, "C4", "RF4")
        event, rows = _split_credit(t, "CBR4", [5, 6])
        assert _void(api, rows[1], scope="single").status_code == 200

        preview = api.get(f"/api/payments/{rows[0].pk}/void-preview/").json()
        assert preview["requeueable"] is False
        assert "already voided" in preview["requeue_blocker"]

        resp = _void(api, rows[0], requeue=True)
        assert resp.status_code == 409
        assert Payment.objects.get(pk=rows[0].pk).voided_at is None
        event.refresh_from_db()
        assert event.status == CoopIpnStatus.RECORDED

    def test_single_scope_is_rejected(self, api, building, coa):
        t = _tenant(building, "C5", "RF5")
        event, rows = _split_credit(t, "CBR5", [5, 6])

        resp = _void(api, rows[0], requeue=True, scope="single")

        assert resp.status_code == 400
        assert Payment.objects.filter(reference="CBR5", voided_at__isnull=True).count() == 2
        event.refresh_from_db()
        assert event.status == CoopIpnStatus.RECORDED

    def test_plain_void_still_leaves_the_credit_recorded(self, api, building, coa, owner):
        t = _tenant(building, "C6", "RF6")
        event, payments = _booked_credit(t, "CBR6", owner=owner)

        preview = api.get(f"/api/payments/{payments[0].pk}/void-preview/").json()
        assert preview["requeueable"] is True

        assert _void(api, payments[0]).status_code == 200
        event.refresh_from_db()
        assert event.status == CoopIpnStatus.RECORDED
        assert event.void_requeue_count == 0


class TestReprocessLeavesRequeuedCreditsAlone:
    @patch("apps.payments.coop_ipn._resolve_tenant")
    def test_requeued_credit_is_not_auto_booked_back(self, resolve, api, building, coa, owner):
        wrong = _tenant(building, "D1", "RP1")
        event, payments = _booked_credit(wrong, "CBP1", owner=owner)
        _void(api, payments[0], requeue=True)
        # The bill ref still resolves to the tenant it was voided from.
        resolve.return_value = (wrong, "bill_ref", True)

        call_command("reprocess_unmatched_ipn")

        event.refresh_from_db()
        assert event.status == CoopIpnStatus.UNMATCHED
        assert not Payment.objects.filter(reference="CBP1", voided_at__isnull=True).exists()
