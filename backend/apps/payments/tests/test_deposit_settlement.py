"""Settling a security deposit at move-out.

The owner states the refund as what is left, an amount or a percentage, and
itemises what is kept: unpaid rent, damages, cleaning. Every shilling of the
deposit must be accounted for, and each part must land in the right place —
the tenant's account, the expense it recovers, or back with the tenant.
"""
import datetime as _dt
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.db.models import Sum
from rest_framework.test import APIClient

from apps.accounts.models import AuditLog
from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.expenses.models import Account, ExpenseCategory
from apps.ledger.checks import run_checks
from apps.ledger.models import JournalLine
from apps.payments import credits
from apps.payments import deposit_settlement as svc
from apps.payments.credits import CreditError
from apps.payments.models import (
    Arrears,
    CreditReason,
    CreditStatus,
    DepositRefundStatus,
    PaymentSource,
    RefundBasis,
)
from apps.payments.monthly_ledger import current_balance
from apps.tenants.deposits import deposit_held_on_books
from apps.tenants.models import Tenant, TenantStatus
from apps.tenants.services import move_out_tenant, record_initial_deposit

D = Decimal
User = get_user_model()

MOVED_OUT = _dt.date(2026, 9, 30)
TODAY = _dt.date(2026, 10, 3)


def _net(code: str) -> Decimal:
    agg = JournalLine.objects.filter(account__code=code).aggregate(d=Sum("debit"), c=Sum("credit"))
    return (agg["d"] or D("0")) - (agg["c"] or D("0"))


def _books_balance() -> None:
    agg = JournalLine.objects.aggregate(d=Sum("debit"), c=Sum("credit"))
    assert agg["d"] == agg["c"]


def _deposit_bank_ties() -> None:
    check = next(c for c in run_checks(today=TODAY) if c.name == "Deposit bank equals deposits held")
    assert check.ok, check.detail


def _category(name, code):
    category, _ = ExpenseCategory.objects.get_or_create(
        name=name, defaults={"account": Account.objects.get(code=code)},
    )
    if category.account.code != code:
        category.account = Account.objects.get(code=code)
        category.save()
    return category


@pytest.fixture
def owner(db):
    return User.objects.create_user(
        username="owner", email="owner@example.com", password="pass12345!", role="owner",
    )


@pytest.fixture
def repairs(db):
    return _category("Repairs & Maintenance", "5200")


@pytest.fixture
def cleaning(db):
    return _category("Cleaning & Garbage Collection", "5220")


@pytest.fixture
def leaver(db, repairs, cleaning):
    """A tenant who paid a 20,000 deposit, owes September's 10,000, and has left."""
    building = Building.objects.create(name="Test Court", code="TCT", total_floors=2)
    unit = Unit.objects.create(
        building=building, label="TC1A", monthly_rent=D("10000"),
        classification=UnitClassification.RESIDENTIAL, status=UnitStatus.OCCUPIED_UNPAID,
    )
    tenant = Tenant.objects.create(
        first_name="Jane", last_name="Tenant", id_number="ID-TEST-1",
        phone="+254700000001", unit=unit, monthly_rent=D("10000"),
        deposit_paid=D("20000"), move_in_date=_dt.date(2026, 7, 1), status=TenantStatus.ACTIVE,
    )
    record_initial_deposit(tenant, received_on=_dt.date(2026, 7, 1))
    Arrears.objects.create(
        tenant=tenant, period_month=9, period_year=2026,
        expected_rent=D("10000"), expected_vat=D("0"), amount_paid=D("0"),
        balance=D("10000"), is_cleared=False,
    )
    move_out_tenant(tenant, move_out_date=MOVED_OUT)
    tenant.refresh_from_db()
    return tenant


def _settle(tenant, owner, deductions, basis=RefundBasis.REMAINDER, **kw):
    return svc.settle_deposit(
        tenant=tenant, settlement_date=TODAY, deductions=deductions, refund_basis=basis,
        actor=owner, today=TODAY, **kw,
    )


UNPAID = {"kind": "unpaid_balance", "amount": "10000"}


@pytest.mark.django_db
class TestRefundBases:
    def test_remainder_refunds_whatever_the_deductions_leave(self, leaver, owner):
        s = _settle(leaver, owner, [UNPAID, {"kind": "cleaning", "amount": "1500", "description": "Deep clean"}])

        assert s.number.startswith("DS-")
        assert s.deposit_held == D("20000.00")
        assert s.deductions_total == D("11500.00")
        assert s.refund_amount == D("8500.00")
        assert s.refund_status == DepositRefundStatus.TO_SEND
        assert [d.description for d in s.deductions.all()] == ["Unpaid rent and charges", "Deep clean"]

    def test_percentage_refund_must_be_matched_by_itemised_deductions(self, leaver, owner):
        with pytest.raises(CreditError, match="5,000.00 of the deposit is not accounted for"):
            _settle(leaver, owner, [UNPAID], RefundBasis.PERCENTAGE, refund_percentage="25")

        s = _settle(
            leaver, owner, [UNPAID, {"kind": "damages", "amount": "5000", "description": "Broken door"}],
            RefundBasis.PERCENTAGE, refund_percentage="25",
        )
        assert s.refund_amount == D("5000.00")
        assert s.refund_percentage == D("25")

    def test_amount_refund_that_overshoots_is_refused(self, leaver, owner):
        with pytest.raises(CreditError, match="come to KES 2,000.00 more than the deposit"):
            _settle(leaver, owner, [UNPAID], RefundBasis.AMOUNT, refund_amount="12000")

    def test_zero_refund_when_the_deposit_is_kept_in_full(self, leaver, owner):
        s = _settle(
            leaver, owner, [UNPAID, {"kind": "damages", "amount": "10000"}],
            RefundBasis.PERCENTAGE, refund_percentage="0",
        )
        assert s.refund_amount == D("0.00")
        assert s.refund_status == DepositRefundStatus.NONE


@pytest.mark.django_db
class TestGuards:
    def test_unpaid_balance_cannot_exceed_what_is_owed(self, leaver, owner):
        with pytest.raises(CreditError, match="owes KES 10,000.00"):
            _settle(leaver, owner, [{"kind": "unpaid_balance", "amount": "12000"}])

    def test_deductions_cannot_exceed_the_deposit(self, leaver, owner):
        with pytest.raises(CreditError, match="more than the KES 20,000.00 deposit"):
            _settle(leaver, owner, [UNPAID, {"kind": "damages", "amount": "15000"}])

    def test_an_active_tenant_cannot_be_settled(self, leaver, owner):
        Tenant.objects.filter(pk=leaver.pk).update(status=TenantStatus.ACTIVE)
        with pytest.raises(CreditError, match="move-out"):
            _settle(leaver, owner, [])

    def test_a_deposit_is_settled_once(self, leaver, owner):
        _settle(leaver, owner, [UNPAID])
        with pytest.raises(CreditError, match="already been settled"):
            _settle(leaver, owner, [])

    def test_other_deduction_needs_a_cost_to_recover(self, leaver, owner):
        with pytest.raises(CreditError, match="Choose the cost"):
            _settle(leaver, owner, [{"kind": "other", "amount": "500"}])


@pytest.mark.django_db
class TestAccountAndBooks:
    def test_unpaid_rent_is_settled_by_a_deposit_credit(self, leaver, owner):
        s = _settle(leaver, owner, [UNPAID, {"kind": "cleaning", "amount": "1500"}])

        credit = s.credit
        assert credit.reason == CreditReason.DEPOSIT_APPLIED
        assert credit.amount == D("10000.00")
        sept = Arrears.objects.get(tenant=leaver, period_month=9)
        assert sept.balance == D("0.00") and sept.is_cleared
        assert current_balance(leaver, today=TODAY) == D("0.00")
        assert credits.account_balance(leaver) == D("0.00")

    def test_ledger_moves_and_deposit_bank_still_ties(self, leaver, owner):
        _settle(
            leaver, owner,
            [UNPAID, {"kind": "damages", "amount": "3000"}, {"kind": "cleaning", "amount": "1500"}],
            sent_on=TODAY, method=PaymentSource.MPESA, reference="QXDEPREF1",
        )

        assert _net("2100") == D("0.00")      # nothing owed back any more
        assert _net("1030") == D("0.00")      # the deposit bank is empty
        assert _net("1040") == D("0.00")      # September's rent settled
        assert _net("5200") == D("-3000.00")  # repairs cost recovered
        assert _net("5220") == D("-1500.00")  # cleaning cost recovered
        # 14,500 kept moves to the operating bank; the 5,500 refund left 1030.
        assert _net("1020") == D("14500.00")
        assert deposit_held_on_books(leaver) == D("20000.00")  # receipts are history
        _books_balance()
        _deposit_bank_ties()

    def test_refund_to_send_posts_only_when_sent(self, leaver, owner):
        s = _settle(leaver, owner, [UNPAID])
        assert _net("2100") == D("-10000.00")
        _deposit_bank_ties()

        with pytest.raises(CreditError, match="transaction reference"):
            svc.mark_refund_sent(s, sent_on=TODAY, method=PaymentSource.MPESA, actor=owner, today=TODAY)
        svc.mark_refund_sent(
            s, sent_on=TODAY, method=PaymentSource.MPESA, reference="QXDEPREF2", actor=owner, today=TODAY,
        )
        s.refresh_from_db()
        assert s.refund_status == DepositRefundStatus.SENT
        assert _net("2100") == D("0.00")
        assert _net("1030") == D("0.00")
        _deposit_bank_ties()

    def test_tenant_refund_fields_follow_the_settlement(self, leaver, owner):
        _settle(leaver, owner, [UNPAID, {"kind": "damages", "amount": "5000"}])
        leaver.refresh_from_db()
        assert leaver.deposit_refund_amount == D("5000.00")
        assert leaver.deposit_refund_percentage == D("25.00")

    def test_settlement_is_audited(self, leaver, owner):
        s = _settle(leaver, owner, [UNPAID])
        log = AuditLog.objects.get(action="tenant.deposit_settle", object_id=s.pk)
        assert log.is_financial


@pytest.mark.django_db
class TestDepositCreditIsNotSpendable:
    def test_it_does_not_show_as_credit_to_refund_or_hold(self, leaver, owner):
        s = _settle(leaver, owner, [UNPAID])
        assert credits.manual_credit_available(leaver) == D("0.00")
        with pytest.raises(CreditError, match="deposit settlement"):
            credits.set_hold(s.credit, hold=True, actor=owner, today=TODAY)
        with pytest.raises(CreditError, match="deposit settlement"):
            credits.void_credit(s.credit, reason="oops", actor=owner, today=TODAY)

    def test_add_credit_does_not_offer_the_reason(self, leaver, owner):
        client = APIClient()
        client.force_authenticate(owner)
        res = client.get("/api/tenant-credits/position/", {"tenant": leaver.pk})
        assert CreditReason.DEPOSIT_APPLIED not in [r["value"] for r in res.json()["reasons"]]


@pytest.mark.django_db
class TestVoid:
    def test_void_puts_the_deposit_and_the_debt_back(self, leaver, owner):
        s = _settle(leaver, owner, [UNPAID, {"kind": "cleaning", "amount": "1500"}])
        svc.void_settlement(s, reason="Wrong damages figure", actor=owner, today=TODAY)

        s.refresh_from_db()
        assert s.is_void
        assert s.credit.status == CreditStatus.VOID
        assert Arrears.objects.get(tenant=leaver, period_month=9).balance == D("10000.00")
        assert _net("2100") == D("-20000.00")
        assert _net("1030") == D("20000.00")
        assert _net("5220") == D("0.00")
        _books_balance()
        _deposit_bank_ties()

        # …and it can be settled again.
        again = _settle(leaver, owner, [UNPAID])
        assert again.refund_amount == D("10000.00")

    def test_a_sent_refund_cannot_be_voided(self, leaver, owner):
        s = _settle(leaver, owner, [UNPAID], sent_on=TODAY, method=PaymentSource.CASH)
        with pytest.raises(CreditError, match="already been sent"):
            svc.void_settlement(s, reason="x", actor=owner, today=TODAY)


@pytest.mark.django_db
class TestApi:
    def test_preview_settle_and_statement(self, leaver, owner, cleaning):
        client = APIClient()
        client.force_authenticate(owner)

        preview = client.get("/api/deposit-settlements/preview/", {"tenant": leaver.pk}).json()
        assert preview["deposit_held"] == "20000.00"
        assert preview["balance_owed"] == "10000.00"
        assert preview["can_settle"] is True
        assert preview["default_categories"]["cleaning"] == cleaning.pk

        res = client.post("/api/deposit-settlements/", {
            "tenant": leaver.pk, "settlement_date": TODAY.isoformat(),
            "deductions": [UNPAID, {"kind": "cleaning", "amount": "2000", "description": "Repaint"}],
            "refund_basis": "percentage", "refund_percentage": "40",
            "method": "mpesa", "paid_to": leaver.phone, "already_sent": False,
        }, format="json")
        assert res.status_code == 201, res.content
        body = res.json()
        assert body["refund_amount"] == "8000.00"
        assert body["credit_number"].startswith("CR-")

        pdf = client.get(f"/api/deposit-settlements/{body['id']}/statement/")
        assert pdf.status_code == 200
        assert pdf["Content-Type"] == "application/pdf"
        assert pdf.content.startswith(b"%PDF")

    def test_mismatch_is_a_400_with_the_gap(self, leaver, owner):
        client = APIClient()
        client.force_authenticate(owner)
        res = client.post("/api/deposit-settlements/", {
            "tenant": leaver.pk, "settlement_date": TODAY.isoformat(),
            "deductions": [UNPAID], "refund_basis": "amount", "refund_amount": "5000",
        }, format="json")
        assert res.status_code == 400
        assert "5,000.00 of the deposit is not accounted for" in res.json()["detail"]

    def test_caretaker_cannot_settle(self, leaver):
        caretaker = User.objects.create_user(
            username="ct", email="ct@example.com", password="pass12345!", role="caretaker",
        )
        client = APIClient()
        client.force_authenticate(caretaker)
        res = client.post("/api/deposit-settlements/", {}, format="json")
        assert res.status_code == 403
