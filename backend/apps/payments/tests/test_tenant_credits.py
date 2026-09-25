"""Tenant credits and refunds: numbered documents, never a typed-in balance.

A credit on account has to reach three places at once — the tenant's balance,
the statement PDF, and the books — and each of the five business cases the
owner signed off must come out right in all three:

  A. overpaid 5,000, carried forward to the next invoice
  B. overpaid 5,000, refunded
  C. a 5,000 billing correction, applied to the next invoice
  D. a manual credit the tenant asks to have paid out
  E. a credit partly applied and the rest refunded (then voided)
"""
import datetime as _dt
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.db.models import Sum
from rest_framework.test import APIClient

from apps.accounts.models import FinancialAuditLog
from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.expenses.models import Account, ExpenseCategory
from apps.ledger.models import JournalEntry, JournalLine
from apps.payments import credits, reporting
from apps.payments.aging import aging_buckets
from apps.payments.credits import CreditError
from apps.payments.models import (
    Arrears,
    CreditReason,
    PaymentSource,
    RefundStatus,
    TenantCredit,
)
from apps.payments.monthly_ledger import OPENING_MARKER, build_monthly_ledger, current_balance
from apps.payments.notifications import _statement_summary_items
from apps.payments.services import available_credit, process_payment
from apps.payments.statement_service import build_statement
from apps.tenants.models import Tenant, TenantStatus

D = Decimal
User = get_user_model()

SEPT = _dt.date(2026, 9, 3)
TODAY = _dt.date(2026, 9, 15)


# ── helpers ──────────────────────────────────────────────────────────────────

def _net(code: str) -> Decimal:
    """Debits less credits on one GL account."""
    agg = JournalLine.objects.filter(account__code=code).aggregate(d=Sum("debit"), c=Sum("credit"))
    return (agg["d"] or D("0")) - (agg["c"] or D("0"))


def _books_balance() -> None:
    agg = JournalLine.objects.aggregate(d=Sum("debit"), c=Sum("credit"))
    assert agg["d"] == agg["c"]


def _money(text: str) -> Decimal:
    return D(text.replace(",", "").replace("(", "-").replace(")", ""))


def _pdf_like() -> SimpleUploadedFile:
    return SimpleUploadedFile("receipt.pdf", b"%PDF-1.4 plumber receipt", content_type="application/pdf")


def _raise(tenant, month, year=2026, rent=None, vat="0"):
    rent = D(rent if rent is not None else tenant.monthly_rent)
    vat = D(vat)
    return Arrears.objects.create(
        tenant=tenant, period_month=month, period_year=year,
        expected_rent=rent, expected_vat=vat, amount_paid=D("0"),
        balance=rent + vat, is_cleared=False,
    )


def _pay(tenant, amount, month, on=SEPT, ref="REF"):
    return process_payment(
        tenant=tenant, amount=D(amount), payment_date=on,
        period_month=month, period_year=2026, source="mpesa", reference=ref,
        idempotency_key=ref,
    )


@pytest.fixture(autouse=True)
def _evidence_in_tmp(settings, tmp_path):
    """Uploaded evidence goes to a throwaway folder, not the real media root."""
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def owner(db):
    return User.objects.create_user(
        username="osoro", email="osoro@test.com", password="pass12345!", role="owner",
    )


@pytest.fixture
def building(db):
    return Building.objects.create(name="Wilkem Edge", code="WED", total_floors=2)


def _let(building, label, rent="10000", classification=UnitClassification.RESIDENTIAL):
    unit = Unit.objects.create(
        building=building, label=label, monthly_rent=D(rent),
        classification=classification, status=UnitStatus.OCCUPIED_UNPAID,
    )
    return Tenant.objects.create(
        first_name=label, last_name="Tenant", id_number=f"ID-{label}",
        phone="+254711111111", unit=unit, monthly_rent=D(rent),
        move_in_date="2026-07-01", status=TenantStatus.ACTIVE,
    )


@pytest.fixture
def house(building):
    return _let(building, "DON1A")


@pytest.fixture
def shop(building):
    return _let(building, "MCG01", rent="10000", classification=UnitClassification.BUSINESS)


@pytest.fixture
def plumbing(db):
    account = Account.objects.get(code="5210")
    category, _ = ExpenseCategory.objects.get_or_create(
        name="Plumbing & Electrical", defaults={"account": account},
    )
    if category.account_id != account.pk:
        category.account = account
        category.save()
    return category


# ── A. overpaid, carried forward ─────────────────────────────────────────────

@pytest.mark.django_db
class TestOverpaymentCarriedForward:
    def test_surplus_settles_the_next_month_and_the_account_squares(self, house):
        _raise(house, 9)
        _pay(house, "15000", 9)
        assert available_credit(house) == D("5000.00")
        assert current_balance(house, today=TODAY) == D("-5000.00")

        october = _raise(house, 10)
        from apps.payments.services import apply_available_credit
        apply_available_credit(october)
        october.refresh_from_db()

        assert october.balance == D("5000.00")
        assert available_credit(house) == D("0.00")
        # The rent roll never counts it twice: 20,000 raised less 15,000 paid.
        assert current_balance(house, today=_dt.date(2026, 10, 10)) == D("5000.00")


# ── B. overpaid, refunded ────────────────────────────────────────────────────

@pytest.mark.django_db
class TestOverpaymentRefunded:
    def test_refund_reverses_the_income_the_overpayment_was_booked_to(self, house, owner):
        _raise(house, 9)
        _pay(house, "15000", 9)
        income_before = _net("4110")

        refund = credits.create_refund(
            tenant=house, amount="5000", method=PaymentSource.MPESA, paid_to=house.phone,
            reference="QX7REFUND", sent_on=TODAY, actor=owner, today=TODAY,
        )

        assert refund.status == RefundStatus.SENT
        assert refund.number.startswith("RF-")
        # Overpaid rent went straight to income when it arrived; paying it back
        # takes it back out of income, not out of 1040.
        assert _net("4110") - income_before == D("5000.00")
        assert _net("1040") == D("0.00")
        assert current_balance(house, today=TODAY) == D("0.00")
        assert available_credit(house) == D("0.00")
        _books_balance()

    def test_commercial_overpayment_refund_gives_the_vat_back(self, shop, owner):
        _raise(shop, 9, vat=D("1600"))
        _pay(shop, "17400", 9)          # 11,600 owed; 5,800 over
        vat_before = _net("2600")

        credits.create_refund(
            tenant=shop, amount="5800", method=PaymentSource.BANK, reference="FT123",
            sent_on=TODAY, actor=owner, today=TODAY,
        )

        assert _net("2600") - vat_before == D("800.00")
        _books_balance()

    def test_cannot_refund_more_than_the_tenant_is_in_credit(self, house, owner):
        _raise(house, 9)
        _pay(house, "15000", 9)
        with pytest.raises(CreditError, match="5,000.00"):
            credits.create_refund(
                tenant=house, amount="6000", method=PaymentSource.CASH,
                sent_on=TODAY, actor=owner, today=TODAY,
            )

    def test_rent_already_invoiced_ahead_is_not_refundable_credit(self, house, owner):
        # October raised early and paid in September: the roll for September
        # reads that as credit, but the tenant owes it — nothing to refund.
        _raise(house, 9)
        _pay(house, "10000", 9, ref="SEP")
        _raise(house, 10)
        _pay(house, "10000", 10, ref="OCT")
        assert current_balance(house, today=TODAY) == D("-10000.00")
        assert credits.refundable_amount(house) == D("0.00")
        with pytest.raises(CreditError, match="Nothing can be refunded"):
            credits.create_refund(
                tenant=house, amount="100", method=PaymentSource.CASH,
                sent_on=TODAY, actor=owner, today=TODAY,
            )


# ── C. billing correction, applied to the next invoice ───────────────────────

@pytest.mark.django_db
class TestBillingCorrection:
    def test_credit_note_on_paid_rent_waits_and_settles_the_next_month(self, house, owner):
        september = _raise(house, 9, rent="15000")      # billed 15,000, agreed 10,000
        _pay(house, "15000", 9)

        credit = credits.issue_credit(
            tenant=house, reason=CreditReason.BILLING_CORRECTION, net_amount="5000",
            credit_date=TODAY, description="September rent billed at 15,000; agreed 10,000",
            arrears=september, actor=owner, today=TODAY,
        )

        assert credit.number.startswith("CN-")
        assert credit.amount == D("5000.00") and credit.vat_amount == D("0.00")
        assert credit.remaining == D("5000.00")        # September is paid; nothing to settle
        entry = JournalEntry.objects.get(source_type="tenant_credit", source_id=credit.pk)
        lines = {ln.account.code: (ln.debit, ln.credit) for ln in entry.lines.all()}
        assert lines == {"4110": (D("5000.00"), D("0")), "1040": (D("0"), D("5000.00"))}

        october = _raise(house, 10)
        applied = credits.apply_account_credits(october, today=_dt.date(2026, 9, 28))
        october.refresh_from_db()
        credit.refresh_from_db()

        assert applied == D("5000.00")
        assert october.balance == D("5000.00")
        assert credit.remaining == D("0.00")
        # Income over the two months is the 20,000 agreed, and 1040 is square.
        assert -_net("4110") == D("15000.00")     # 15,000 cash - 5,000 CN + 5,000 applied
        assert _net("1040") == D("0.00")
        _books_balance()

    def test_commercial_credit_note_carries_the_charges_vat_and_nets_to_nothing(self, shop, owner):
        september = _raise(shop, 9, vat=D("1600"))     # 11,600 unpaid

        credit = credits.issue_credit(
            tenant=shop, reason=CreditReason.BILLING_CORRECTION, net_amount="2000",
            credit_date=TODAY, description="Rent overbilled", arrears=september,
            actor=owner, today=TODAY,
        )
        september.refresh_from_db()

        assert (credit.net_amount, credit.vat_amount, credit.amount) == (
            D("2000.00"), D("320.00"), D("2320.00"),
        )
        # Applied at once to the very charge it corrects.
        assert september.balance == D("9280.00")
        # Nothing was recognised on that unpaid rent, so nothing is reduced.
        for code in ("4120", "2600", "1040"):
            assert _net(code) == D("0.00"), code
        _books_balance()

    def test_a_charge_cannot_be_credited_beyond_what_it_was(self, house, owner):
        september = _raise(house, 9)
        with pytest.raises(CreditError, match="10,000.00"):
            credits.issue_credit(
                tenant=house, reason=CreditReason.BILLING_CORRECTION, net_amount="10001",
                credit_date=TODAY, description="x", arrears=september, actor=owner, today=TODAY,
            )

    def test_an_opening_balance_is_not_a_charge_to_correct(self, house, owner):
        opening = _raise(house, 7, rent="4000")
        opening.waive_notes = OPENING_MARKER
        opening.save()
        with pytest.raises(CreditError, match="brought forward"):
            credits.issue_credit(
                tenant=house, reason=CreditReason.BILLING_CORRECTION, net_amount="1000",
                credit_date=TODAY, description="x", arrears=opening, actor=owner, today=TODAY,
            )


# ── D. a manual credit paid out ──────────────────────────────────────────────

@pytest.mark.django_db
class TestManualCreditPaidOut:
    def test_tenant_paid_repair_is_an_expense_and_the_refund_pays_it(self, house, owner, plumbing):
        credit = credits.issue_credit(
            tenant=house, reason=CreditReason.TENANT_PAID_COST, net_amount="5000",
            credit_date=TODAY, description="Plumber paid by tenant for burst pipe",
            expense_category=plumbing, evidence=_pdf_like(), evidence_name="receipt.pdf",
            actor=owner, today=TODAY,
        )
        assert credit.number.startswith("CR-")
        assert _net("5210") == D("5000.00")
        assert _net("1040") == D("-5000.00")          # money owed back to the tenant

        credits.create_refund(
            tenant=house, amount="5000", method=PaymentSource.MPESA, reference="QXPLUMB",
            sent_on=TODAY, credit=credit, actor=owner, today=TODAY,
        )

        # Exactly as if Wilkem had paid the plumber: expense up, bank down.
        assert _net("5210") == D("5000.00")
        assert _net("1020") == D("-5000.00")
        assert _net("1040") == D("0.00")
        assert _net("4110") == D("0.00")              # no income touched
        _books_balance()

    def test_the_reason_decides_the_account(self, house, owner):
        credits.issue_credit(
            tenant=house, reason=CreditReason.OPENING_CREDIT, net_amount="3000",
            credit_date=TODAY, description="Credit owed at cutover",
            evidence=_pdf_like(), evidence_name="cutover.pdf", actor=owner, today=TODAY,
        )
        assert _net("3300") == D("3000.00")
        assert _net("4110") == D("0.00")

    def test_supporting_document_is_optional(self, house, owner, plumbing):
        # The owner is the only user; a rule that blocks a credit until a photo
        # is to hand only invites a worse workaround. What was attached — or
        # that nothing was — stays on the record either way.
        credit = credits.issue_credit(
            tenant=house, reason=CreditReason.TENANT_PAID_COST, net_amount="5000",
            credit_date=TODAY, description="Plumber paid by tenant",
            expense_category=plumbing, actor=owner, today=TODAY,
        )
        assert credit.evidence_name == ""
        assert _net("5210") == D("5000.00")


# ── E. partly applied, the rest refunded, then voided ────────────────────────

@pytest.mark.django_db
class TestPartlyAppliedThenRefunded:
    def _setup(self, house, owner):
        september = _raise(house, 9)
        _pay(house, "7000", 9)                          # 3,000 still owed
        credit = credits.issue_credit(
            tenant=house, reason=CreditReason.RENT_CONCESSION, net_amount="5000",
            credit_date=TODAY, description="Water outage — agreed reduction",
            arrears=september, actor=owner, today=TODAY,
        )
        september.refresh_from_db()
        return september, credit

    def test_applied_then_the_rest_refunded(self, house, owner):
        september, credit = self._setup(house, owner)
        assert september.balance == D("0.00")
        assert (credit.amount_applied, credit.remaining) == (D("3000.00"), D("2000.00"))

        credits.create_refund(
            tenant=house, amount="2000", method=PaymentSource.MPESA, reference="QXREST",
            sent_on=TODAY, actor=owner, today=TODAY,
        )
        credit.refresh_from_db()

        assert (credit.amount_applied, credit.amount_refunded, credit.remaining) == (
            D("3000.00"), D("2000.00"), D("0.00"),
        )
        assert current_balance(house, today=TODAY) == D("0.00")
        assert _net("1040") == D("0.00")
        _books_balance()

    def test_voiding_reopens_the_rent_and_the_tenant_owes_the_refund(self, house, owner):
        september, credit = self._setup(house, owner)
        credits.create_refund(
            tenant=house, amount="2000", method=PaymentSource.MPESA, reference="QXREST",
            sent_on=TODAY, actor=owner, today=TODAY,
        )

        preview = credits.void_preview(credit)
        assert preview["reopened_total"] == D("3000.00")
        assert preview["refunded_kept"] == D("2000.00")

        credits.void_credit(credit, reason="Outage was the tenant's own fault", actor=owner, today=TODAY)
        credit.refresh_from_db()
        september.refresh_from_db()

        assert credit.status == "void"
        assert september.balance == D("3000.00")
        # 3,000 rent re-opened + the 2,000 that was paid out.
        assert current_balance(house, today=TODAY) == D("5000.00")
        assert credits.account_balance(house) == D("5000.00")
        reversal = JournalEntry.objects.get(source_type="tenant_credit", source_id=credit.pk, kind="reversal")
        assert reversal.date == TODAY
        _books_balance()

    def test_a_voided_credit_leaves_the_statement(self, house, owner):
        _, credit = self._setup(house, owner)
        credits.void_credit(credit, reason="Entered in error", actor=owner, today=TODAY)
        rows = build_statement(house, statement_date=TODAY)["rows"]
        assert not any(credit.number in r["description"] for r in rows)


# ── holds, reservations, double use ──────────────────────────────────────────

@pytest.mark.django_db
class TestControls:
    def test_held_credit_is_not_applied_until_released(self, house, owner):
        september = _raise(house, 9)
        credit = credits.issue_credit(
            tenant=house, reason=CreditReason.RENT_CONCESSION, net_amount="4000",
            credit_date=TODAY, description="Discount", arrears=september,
            hold=True, actor=owner, today=TODAY,
        )
        september.refresh_from_db()
        assert september.balance == D("10000.00")
        assert credits.apply_account_credits(_raise(house, 10), today=TODAY) == D("0.00")

        credits.set_hold(credit, hold=False, actor=owner, today=TODAY)
        september.refresh_from_db()
        assert september.balance == D("6000.00")

    def test_a_refund_to_send_reserves_the_credit_and_cancelling_releases_it(self, house, owner):
        credit = credits.issue_credit(
            tenant=house, reason=CreditReason.OPENING_CREDIT, net_amount="5000",
            credit_date=TODAY, description="Owed at cutover", evidence=_pdf_like(),
            evidence_name="c.pdf", actor=owner, today=TODAY,
        )
        refund = credits.create_refund(
            tenant=house, amount="5000", method=PaymentSource.MPESA, actor=owner, today=TODAY,
        )
        assert refund.status == RefundStatus.SCHEDULED
        assert not JournalEntry.objects.filter(source_type="tenant_refund").exists()
        # Reserved: billing cannot use it, and it cannot be refunded twice.
        assert credits.apply_account_credits(_raise(house, 10), today=TODAY) == D("0.00")
        with pytest.raises(CreditError):
            credits.create_refund(
                tenant=house, amount="1", method=PaymentSource.CASH, sent_on=TODAY,
                actor=owner, today=TODAY,
            )

        credits.cancel_refund(refund, reason="Tenant will take it off rent", actor=owner)
        credit.refresh_from_db()
        assert credit.remaining == D("5000.00")

    def test_mark_as_sent_posts_on_the_day_the_money_left(self, house, owner):
        credits.issue_credit(
            tenant=house, reason=CreditReason.OPENING_CREDIT, net_amount="5000",
            credit_date=TODAY, description="Owed at cutover", evidence=_pdf_like(),
            evidence_name="c.pdf", actor=owner, today=TODAY,
        )
        refund = credits.create_refund(
            tenant=house, amount="5000", method=PaymentSource.MPESA, actor=owner, today=TODAY,
        )
        with pytest.raises(CreditError, match="reference"):
            credits.mark_refund_sent(refund, sent_on=TODAY, actor=owner, today=TODAY)
        credits.mark_refund_sent(refund, sent_on=TODAY, reference="QXSENT", actor=owner, today=TODAY)
        entry = JournalEntry.objects.get(source_type="tenant_refund", source_id=refund.pk)
        assert entry.date == TODAY

    def test_voiding_a_refund_puts_the_credit_back(self, house, owner):
        credit = credits.issue_credit(
            tenant=house, reason=CreditReason.OPENING_CREDIT, net_amount="5000",
            credit_date=TODAY, description="Owed at cutover", evidence=_pdf_like(),
            evidence_name="c.pdf", actor=owner, today=TODAY,
        )
        refund = credits.create_refund(
            tenant=house, amount="5000", method=PaymentSource.BANK, reference="FT9",
            sent_on=TODAY, actor=owner, today=TODAY,
        )
        credits.void_refund(refund, reason="Bank returned the transfer", actor=owner, today=TODAY)
        credit.refresh_from_db()
        assert credit.remaining == D("5000.00")
        assert _net("1020") == D("0.00")
        assert current_balance(house, today=TODAY) == D("-5000.00")

    def test_the_database_refuses_a_credit_used_twice(self, house, owner):
        credit = credits.issue_credit(
            tenant=house, reason=CreditReason.OPENING_CREDIT, net_amount="5000",
            credit_date=TODAY, description="Owed", evidence=_pdf_like(),
            evidence_name="c.pdf", hold=True, actor=owner, today=TODAY,
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            TenantCredit.objects.filter(pk=credit.pk).update(
                amount_applied=D("3000"), amount_refunded=D("2001"),
            )

    def test_a_future_dated_credit_is_refused(self, house, owner):
        with pytest.raises(CreditError, match="future"):
            credits.issue_credit(
                tenant=house, reason=CreditReason.OPENING_CREDIT, net_amount="100",
                credit_date=TODAY + _dt.timedelta(days=1), description="x",
                evidence=_pdf_like(), evidence_name="c.pdf", actor=owner, today=TODAY,
            )

    def test_every_step_is_audited(self, house, owner):
        credit = credits.issue_credit(
            tenant=house, reason=CreditReason.OPENING_CREDIT, net_amount="5000",
            credit_date=TODAY, description="Owed", evidence=_pdf_like(),
            evidence_name="c.pdf", actor=owner, today=TODAY,
        )
        refund = credits.create_refund(
            tenant=house, amount="1000", method=PaymentSource.CASH, sent_on=TODAY,
            actor=owner, today=TODAY,
        )
        credits.void_refund(refund, reason="Never handed over", actor=owner, today=TODAY)
        credits.void_credit(credit, reason="Duplicate", actor=owner, today=TODAY)
        actions = list(FinancialAuditLog.objects.order_by("id").values_list("action", flat=True))
        assert actions == ["credit.issue", "refund.record", "refund.void", "credit.void"]
        assert all(
            row.actor_id == owner.pk for row in FinancialAuditLog.objects.all()
        )
        assert credit.approval_mode == "owner_self" and credit.approved_by_id == owner.pk


# ── the statement, the roll and aging all agree ──────────────────────────────

@pytest.mark.django_db
class TestStatementAndReports:
    def test_statement_rows_summary_and_sms_all_foot(self, shop, owner):
        september = _raise(shop, 9, vat=D("1600"))
        _pay(shop, "11600", 9, on=_dt.date(2026, 9, 2))
        credit = credits.issue_credit(
            tenant=shop, reason=CreditReason.BILLING_CORRECTION, net_amount="2000",
            credit_date=_dt.date(2026, 9, 10), description="Rent overbilled", arrears=september,
            actor=owner, today=TODAY,
        )
        credits.create_refund(
            tenant=shop, amount="1000", method=PaymentSource.MPESA, reference="QXPART",
            sent_on=TODAY, credit=credit, actor=owner, today=TODAY,
        )

        s = build_statement(shop, statement_date=TODAY, period=(2026, 9))
        descriptions = [r["description"] for r in s["rows"]]
        assert f"Credit Note {credit.number} - Rent overbilled" in descriptions
        assert "16% VAT credited" in descriptions
        assert any(d.startswith("Refund Paid RF-") and "QXPART" in d for d in descriptions)

        # Closing balance: in credit by 2,320 - 1,000.
        assert s["total_due_value"] == D("-1320.00")
        assert s["in_credit"] and s["credit_on_account"] == "1,320.00"

        # The PDF summary box foots.
        box = (
            _money(s["arrears_others"]) + _money(s["current_month_rent"]) + _money(s["vat_on_rent"])
            - _money(s["payments_received"]) - _money(s["account_credits"]) + _money(s["refunds_paid"])
        )
        assert box == s["total_due_value"]

        # The SMS / email summary foots to the Unpaid Balance.
        total = D("0")
        for _short, label, amount in _statement_summary_items(s):
            total += -_money(amount) if label.startswith("Less:") else _money(amount)
        assert total == s["total_due_value"]

    def test_pdf_renders_credit_on_account(self, house, owner):
        from django.template.loader import render_to_string

        credits.issue_credit(
            tenant=house, reason=CreditReason.OPENING_CREDIT, net_amount="2500",
            credit_date=TODAY, description="Owed at cutover", evidence=_pdf_like(),
            evidence_name="c.pdf", actor=owner, today=TODAY,
        )
        html = render_to_string("payments/statement_pdf.html", build_statement(house, statement_date=TODAY))
        assert "CREDIT ON ACCOUNT" in html
        assert "Credit on Account:" in html          # not "Total KES: Ksh-2,500.00"
        assert "Less: Credits" in html
        # Template comments must never print on a tenant's statement.
        assert "{#" not in html and "#}" not in html

    def test_rent_roll_and_aging_carry_credits_and_refunds(self, house, owner):
        _raise(house, 9)
        credits.issue_credit(
            tenant=house, reason=CreditReason.OPENING_CREDIT, net_amount="4000",
            credit_date=TODAY, description="Owed", evidence=_pdf_like(),
            evidence_name="c.pdf", actor=owner, today=TODAY,
        )
        rows = build_monthly_ledger(house, today=TODAY)
        september = rows[-1]
        assert september["credits"] == "4000.00"
        assert D(september["balance"]) == D("6000.00") == current_balance(house, today=TODAY)
        assert aging_buckets([house], today=TODAY)[house.pk]["total"] == D("6000.00")


# ── the reports read credits the way the chart of accounts does ─────────────

@pytest.mark.django_db
class TestReports:
    """Income, expenses and the P&L have to move with the credits.

    The Accounting page reads the ledger, so it follows a credit the moment it
    posts. The Reports page is built from Payment/Expense rows, so it is told
    about credits through `apps.payments.reporting`.
    """

    def _client(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_a_credit_note_takes_income_back_out(self, house, owner):
        september = _raise(house, 9, rent="15000")
        _pay(house, "15000", 9)
        credits.issue_credit(
            tenant=house, reason=CreditReason.BILLING_CORRECTION, net_amount="5000",
            credit_date=TODAY, description="Overbilled", arrears=september,
            actor=owner, today=TODAY,
        )
        assert reporting.credit_notes_net(9, 2026) == D("5000.00")
        assert reporting.income_adjustment(9, 2026) == D("-5000.00")

    def test_rent_settled_by_credit_is_income_even_though_no_cash_came(self, house, owner):
        _raise(house, 9)
        credits.issue_credit(
            tenant=house, reason=CreditReason.OPENING_CREDIT, net_amount="4000",
            credit_date=TODAY, description="Owed at cutover", actor=owner, today=TODAY,
        )
        # Applied to September rent on issue: earned now, with no Payment row.
        assert reporting.credit_applied_net(9, 2026) == D("4000.00")
        assert reporting.income_adjustment(9, 2026) == D("4000.00")

    def test_a_commercial_credit_application_leaves_the_vat_out_of_income(self, shop, owner):
        _raise(shop, 9, vat=D("1600"))
        credits.issue_credit(
            tenant=shop, reason=CreditReason.OPENING_CREDIT, net_amount="5800",
            credit_date=TODAY, description="Owed at cutover", actor=owner, today=TODAY,
        )
        # 5,800 settles rent of 5,000 plus 800 VAT owed to KRA.
        assert reporting.credit_applied_net(9, 2026) == D("5000.00")

    def test_refunding_overpaid_rent_reverses_the_income(self, house, owner):
        _raise(house, 9)
        _pay(house, "15000", 9)
        credits.create_refund(
            tenant=house, amount="5000", method=PaymentSource.MPESA, reference="QX1",
            sent_on=TODAY, actor=owner, today=TODAY,
        )
        assert reporting.refunded_income_net(9, 2026) == D("5000.00")
        assert reporting.income_adjustment(9, 2026) == D("-5000.00")

    def test_refunding_a_credit_is_not_an_income_event(self, house, owner):
        credits.issue_credit(
            tenant=house, reason=CreditReason.OPENING_CREDIT, net_amount="5000",
            credit_date=TODAY, description="Owed at cutover", actor=owner, today=TODAY,
        )
        credits.create_refund(
            tenant=house, amount="5000", method=PaymentSource.CASH,
            sent_on=TODAY, actor=owner, today=TODAY,
        )
        assert reporting.refunded_income_net(9, 2026) == D("0.00")

    def test_a_cost_the_tenant_paid_is_an_expense_of_ours(self, house, owner, plumbing):
        credits.issue_credit(
            tenant=house, reason=CreditReason.TENANT_PAID_COST, net_amount="5000",
            credit_date=TODAY, description="Plumber", expense_category=plumbing,
            actor=owner, today=TODAY,
        )
        assert reporting.expense_additions(9, 2026) == {"Plumbing & Electrical": D("5000.00")}
        assert reporting.expense_addition_total(9, 2026) == D("5000.00")
        # ...and it is not mistaken for an income movement.
        assert reporting.income_adjustment(9, 2026) == D("0.00")

    def test_an_opening_credit_is_equity_so_it_moves_neither(self, house, owner):
        credits.issue_credit(
            tenant=house, reason=CreditReason.OPENING_CREDIT, net_amount="3000",
            credit_date=TODAY, description="Owed at cutover", hold=True,
            actor=owner, today=TODAY,
        )
        assert reporting.income_adjustment(9, 2026) == D("0.00")
        assert reporting.expense_addition_total(9, 2026) == D("0.00")

    def test_a_voided_credit_leaves_the_reports(self, house, owner):
        september = _raise(house, 9, rent="15000")
        _pay(house, "15000", 9)
        credit = credits.issue_credit(
            tenant=house, reason=CreditReason.BILLING_CORRECTION, net_amount="5000",
            credit_date=TODAY, description="Overbilled", arrears=september,
            actor=owner, today=TODAY,
        )
        credits.void_credit(credit, reason="Entered in error", actor=owner, today=TODAY)
        assert reporting.income_adjustment(9, 2026) == D("0.00")

    def test_profit_and_loss_reports_the_credit(self, house, owner, plumbing):
        september = _raise(house, 9, rent="15000")
        _pay(house, "15000", 9)
        credits.issue_credit(
            tenant=house, reason=CreditReason.BILLING_CORRECTION, net_amount="5000",
            credit_date=TODAY, description="Overbilled", arrears=september,
            actor=owner, today=TODAY,
        )
        credits.issue_credit(
            tenant=house, reason=CreditReason.TENANT_PAID_COST, net_amount="2000",
            credit_date=TODAY, description="Plumber", expense_category=plumbing,
            actor=owner, today=TODAY,
        )
        body = self._client(owner).get("/api/reports/profit-loss/?month=9&year=2026").json()
        assert body["income"] == 10000.0                     # 15,000 cash less the 5,000 credit
        assert {"category": "Plumbing & Electrical", "amount": 2000.0} in body["expense_breakdown"]
        assert body["net_profit"] == 8000.0

    def test_expense_breakdown_lists_the_cost_the_tenant_paid(self, house, owner, plumbing):
        credits.issue_credit(
            tenant=house, reason=CreditReason.TENANT_PAID_COST, net_amount="2500",
            credit_date=TODAY, description="Plumber", expense_category=plumbing,
            actor=owner, today=TODAY,
        )
        body = self._client(owner).get("/api/reports/expense-breakdown/?month=9&year=2026").json()
        row = next(r for r in body["categories"] if r["category"] == "Plumbing & Electrical")
        assert row["total"] == 2500.0 and row["count"] == 1
        assert body["total_expenses"] == 2500.0

    def test_annual_income_summary_follows_the_credit(self, house, owner):
        september = _raise(house, 9, rent="15000")
        _pay(house, "15000", 9)
        credits.issue_credit(
            tenant=house, reason=CreditReason.BILLING_CORRECTION, net_amount="5000",
            credit_date=TODAY, description="Overbilled", arrears=september,
            actor=owner, today=TODAY,
        )
        body = self._client(owner).get("/api/reports/annual-income/?year=2026").json()
        september_row = next(r for r in body["monthly"] if r["month"] == 9)
        assert september_row["total"] == 10000.0

    def test_the_ledger_and_the_report_tell_the_same_story(self, house, owner):
        september = _raise(house, 9, rent="15000")
        _pay(house, "15000", 9)
        credits.issue_credit(
            tenant=house, reason=CreditReason.BILLING_CORRECTION, net_amount="5000",
            credit_date=TODAY, description="Overbilled", arrears=september,
            actor=owner, today=TODAY,
        )
        report = self._client(owner).get("/api/reports/profit-loss/?month=9&year=2026").json()
        # 4110 carries the cash less the credit note; the report must agree.
        assert D(str(report["income"])) == -_net("4110")


# ── the API the tenant page uses ─────────────────────────────────────────────

@pytest.mark.django_db
class TestApi:
    def _client(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_add_credit_with_evidence_then_refund_it(self, house, owner, plumbing):
        client = self._client(owner)
        resp = client.post("/api/tenant-credits/", {
            "tenant": house.pk, "reason": "tenant_paid_cost", "amount": "5000",
            "credit_date": TODAY.isoformat(), "description": "Plumber paid by tenant",
            "expense_category": plumbing.pk, "evidence": _pdf_like(),
        }, format="multipart")
        assert resp.status_code == 201, resp.content
        body = resp.json()
        assert body["number"].startswith("CR-")
        assert body["status_display"] == "Available"
        assert body["history"][0]["kind"] == "issued"

        position = client.get(f"/api/tenant-credits/position/?tenant={house.pk}").json()
        assert D(position["refundable"]) == D("5000.00")
        assert any(r["value"] == "tenant_paid_cost" and r["needs_category"] for r in position["reasons"])

        resp = client.post("/api/refunds/", {
            "tenant": house.pk, "amount": "5000", "method": "mpesa", "reference": "QXAPI",
            "already_sent": True, "sent_on": TODAY.isoformat(),
        }, format="json")
        assert resp.status_code == 201, resp.content
        assert resp.json()["status"] == "sent"

        evidence = client.get(f"/api/tenant-credits/{body['id']}/evidence/")
        assert evidence.status_code == 200

    def test_business_rule_errors_come_back_as_plain_messages(self, house, owner):
        resp = self._client(owner).post("/api/tenant-credits/", {
            "tenant": house.pk, "reason": "billing_correction", "amount": "5000",
            "credit_date": TODAY.isoformat(), "description": "No charge chosen",
        }, format="multipart")
        assert resp.status_code == 400
        assert "one charge" in resp.json()["detail"]

    def test_void_needs_a_reason(self, house, owner):
        credit = credits.issue_credit(
            tenant=house, reason=CreditReason.OPENING_CREDIT, net_amount="100",
            credit_date=TODAY, description="Owed", evidence=_pdf_like(),
            evidence_name="c.pdf", actor=owner, today=TODAY,
        )
        resp = self._client(owner).post(f"/api/tenant-credits/{credit.pk}/void/", {"reason": ""}, format="json")
        assert resp.status_code == 400

    def test_only_the_owner_can_add_credit(self, house):
        accountant = User.objects.create_user(
            username="clerk", email="clerk@test.com", password="pass12345!", role="accountant",
        )
        resp = self._client(accountant).post("/api/tenant-credits/", {
            "tenant": house.pk, "reason": "opening_credit", "amount": "1",
            "credit_date": TODAY.isoformat(), "description": "x",
        }, format="multipart")
        assert resp.status_code == 403
