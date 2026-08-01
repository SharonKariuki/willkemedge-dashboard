"""Regression tests for the handover audit findings.

Each test pins one previously-broken behaviour. They are named for the finding
they close so a future change that reopens one is obvious from the failure.

C1  cross-tenant reference collision swallowed a payment
C2  commercial VAT cleared arrears early and spilled into the next period
C3  voiding a payment never reached the ledger / corrupted deposit accounts
C4  deposits and late fees settled rent arrears
C5  every authenticated user could record, waive and reconcile money
C6  /mock/ minted real financial records in production
H1  overpayment credit was floored to zero and never carried forward
H2  waived debt kept appearing on the tenant statement
H3  deposits were counted twice on the statement
H5  reversal matching was an unanchored scan over the newest 500 events
H7  no audit trail on financial mutations
"""
import datetime as dt
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.accounts.models import FinancialAuditLog, Role
from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.payments.models import Arrears, Payment, PaymentType
from apps.payments.services import (
    IdempotencyConflict,
    allocate_payment_fifo,
    available_credit,
    process_payment,
    void_payment,
)
from apps.tenants.models import Tenant, TenantStatus

User = get_user_model()
PAY_DATE = dt.date(2026, 6, 5)


# ── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def coa(db):
    call_command("seed_coa")


@pytest.fixture
def building(db):
    return Building.objects.create(name="Audit Block", address="Nairobi")


def _unit(building, label, rent, classification=UnitClassification.RESIDENTIAL):
    return Unit.objects.create(
        building=building, label=label, monthly_rent=rent,
        classification=classification, status=UnitStatus.OCCUPIED_UNPAID,
    )


def _tenant(unit, rent, idn):
    return Tenant.objects.create(
        first_name="T", last_name=idn, id_number=idn, phone="254700000000",
        unit=unit, monthly_rent=rent, move_in_date=dt.date(2026, 1, 1),
        status=TenantStatus.ACTIVE,
    )


def _arrear(tenant, month, year, rent, vat=Decimal("0")):
    return Arrears.objects.create(
        tenant=tenant, period_month=month, period_year=year,
        expected_rent=rent, expected_vat=vat, amount_paid=0,
        balance=rent + vat, is_cleared=False,
    )


def _client(role=Role.OWNER):
    user = User.objects.create_user(
        username=f"u{role}", email=f"{role}@test.com",
        password="Str0ngPassw0rd!x", role=role,
    )
    api = APIClient()
    api.force_authenticate(user=user)
    return api, user


# ── C1 — idempotency is scoped to the tenant ────────────────────────────────

class TestC1IdempotencyScope:
    def test_same_reference_for_two_tenants_records_both(self, building):
        """A shared receipt-book number must not collapse two tenants' money."""
        t1 = _tenant(_unit(building, "A1", Decimal("10000")), Decimal("10000"), "C1A")
        t2 = _tenant(_unit(building, "A2", Decimal("10000")), Decimal("10000"), "C1B")

        p1 = process_payment(
            tenant=t1, amount=Decimal("10000"), payment_date=PAY_DATE,
            period_month=6, period_year=2026, reference="001", idempotency_key="001",
        )
        p2 = process_payment(
            tenant=t2, amount=Decimal("9000"), payment_date=PAY_DATE,
            period_month=6, period_year=2026, reference="001", idempotency_key="001",
        )
        assert p1.pk != p2.pk
        assert p2.tenant_id == t2.pk
        assert p2.amount == Decimal("9000.00")

    def test_true_replay_is_still_idempotent(self, building):
        t = _tenant(_unit(building, "A3", Decimal("10000")), Decimal("10000"), "C1C")
        kwargs = dict(
            tenant=t, amount=Decimal("10000"), payment_date=PAY_DATE,
            period_month=6, period_year=2026, reference="MP1", idempotency_key="MP1",
        )
        assert process_payment(**kwargs).pk == process_payment(**kwargs).pk
        assert Payment.objects.filter(tenant=t).count() == 1

    def test_same_key_different_amount_conflicts(self, building):
        """A key reused for a *different* payment is an error, not a silent drop."""
        t = _tenant(_unit(building, "A4", Decimal("10000")), Decimal("10000"), "C1D")
        process_payment(
            tenant=t, amount=Decimal("10000"), payment_date=PAY_DATE,
            period_month=6, period_year=2026, reference="R9", idempotency_key="R9",
        )
        with pytest.raises(IdempotencyConflict):
            process_payment(
                tenant=t, amount=Decimal("7500"), payment_date=PAY_DATE,
                period_month=6, period_year=2026, reference="R9", idempotency_key="R9",
            )

    def test_api_returns_409_on_collision(self, building, coa):
        api, _ = _client()
        t = _tenant(_unit(building, "A5", Decimal("10000")), Decimal("10000"), "C1E")
        body = {
            "tenant": t.pk, "amount": "10000.00", "payment_date": PAY_DATE.isoformat(),
            "period_month": 6, "period_year": 2026, "source": "cash", "reference": "DUP1",
        }
        assert api.post("/api/payments/", body, format="json").status_code == 201
        resp = api.post("/api/payments/", {**body, "amount": "4000.00"}, format="json")
        assert resp.status_code == 409
        assert "existing_payment_id" in resp.json()


# ── C2 — commercial VAT ─────────────────────────────────────────────────────

class TestC2CommercialVat:
    def test_gross_payment_clears_exactly_and_no_more(self, building):
        unit = _unit(building, "MR1", Decimal("24000"), UnitClassification.BUSINESS)
        t = _tenant(unit, Decimal("24000"), "C2A")
        _arrear(t, 6, 2026, Decimal("24000"), Decimal("3840"))

        process_payment(
            tenant=t, amount=Decimal("27840"), payment_date=PAY_DATE,
            period_month=6, period_year=2026, source="mpesa", reference="C2A",
        )
        ar = Arrears.objects.get(tenant=t, period_month=6)
        assert ar.expected_vat == Decimal("3840.00")
        assert ar.expected_total == Decimal("27840.00")
        assert ar.balance == Decimal("0.00")
        assert ar.is_cleared is True

    def test_base_rent_only_leaves_the_vat_outstanding(self, building):
        """Paying 24,000 against a 27,840 obligation must NOT clear the period."""
        unit = _unit(building, "MR2", Decimal("24000"), UnitClassification.BUSINESS)
        t = _tenant(unit, Decimal("24000"), "C2B")
        _arrear(t, 6, 2026, Decimal("24000"), Decimal("3840"))

        process_payment(
            tenant=t, amount=Decimal("24000"), payment_date=PAY_DATE,
            period_month=6, period_year=2026, source="mpesa", reference="C2B",
        )
        ar = Arrears.objects.get(tenant=t, period_month=6)
        assert ar.balance == Decimal("3840.00")
        assert ar.is_cleared is False

    def test_fifo_does_not_spill_vat_into_the_next_period(self, building):
        unit = _unit(building, "MR3", Decimal("24000"), UnitClassification.BUSINESS)
        t = _tenant(unit, Decimal("24000"), "C2C")
        _arrear(t, 5, 2026, Decimal("24000"), Decimal("3840"))

        payments = allocate_payment_fifo(
            tenant=t, amount=Decimal("27840"), payment_date=PAY_DATE,
            source="mpesa", reference="TXNC2C", idempotency_key="TXNC2C",
        )
        # One chunk, fully settling May — the VAT is part of May's obligation,
        # not June's rent.
        assert len(payments) == 1
        assert payments[0].amount == Decimal("27840")
        assert (payments[0].period_month, payments[0].period_year) == (5, 2026)
        assert Arrears.objects.get(tenant=t, period_month=5).is_cleared is True

    def test_residential_is_unaffected(self, building):
        t = _tenant(_unit(building, "R1", Decimal("10000")), Decimal("10000"), "C2D")
        _arrear(t, 6, 2026, Decimal("10000"))
        process_payment(
            tenant=t, amount=Decimal("10000"), payment_date=PAY_DATE,
            period_month=6, period_year=2026, reference="C2D",
        )
        ar = Arrears.objects.get(tenant=t, period_month=6)
        assert ar.expected_vat == Decimal("0.00")
        assert ar.is_cleared is True

    def test_arrears_balance_reconciles_with_the_statement(self, building):
        """The two figures the business quotes a tenant must agree."""
        from apps.payments.statement_service import build_statement

        unit = _unit(building, "MR4", Decimal("24000"), UnitClassification.BUSINESS)
        t = _tenant(unit, Decimal("24000"), "C2E")
        _arrear(t, 6, 2026, Decimal("24000"), Decimal("3840"))
        process_payment(
            tenant=t, amount=Decimal("20000"), payment_date=PAY_DATE,
            period_month=6, period_year=2026, reference="C2E",
        )
        ar = Arrears.objects.get(tenant=t, period_month=6)
        statement = build_statement(t, statement_date=PAY_DATE, as_of=PAY_DATE)
        assert ar.balance == statement["total_due_value"]


# ── C3 — void reaches the ledger ────────────────────────────────────────────

class TestC3Void:
    def test_void_of_commercial_payment_posts_a_reversal(self, building, coa):
        from apps.ledger.models import JournalEntry, PostingFailure

        unit = _unit(building, "MR5", Decimal("24000"), UnitClassification.BUSINESS)
        t = _tenant(unit, Decimal("24000"), "C3A")
        p = process_payment(
            tenant=t, amount=Decimal("27840"), payment_date=PAY_DATE,
            period_month=6, period_year=2026, reference="C3A",
        )
        void_payment(p, reason="keyed twice")
        p.refresh_from_db()

        assert p.is_void is True
        # Original entry preserved, reversal entry added.
        assert JournalEntry.objects.filter(
            source_type="payment", source_id=p.pk, kind="normal").exists()
        assert JournalEntry.objects.filter(
            source_type="payment", source_id=p.pk, kind="reversal").exists()
        assert not PostingFailure.objects.filter(
            source_type="payment", source_id=p.pk, resolved=False).exists()

    def test_void_nets_the_ledger_to_zero(self, building, coa):
        from apps.ledger.models import JournalLine

        t = _tenant(_unit(building, "R2", Decimal("10000")), Decimal("10000"), "C3B")
        p = process_payment(
            tenant=t, amount=Decimal("10000"), payment_date=PAY_DATE,
            period_month=6, period_year=2026, reference="C3B",
        )
        void_payment(p, reason="duplicate")

        lines = JournalLine.objects.filter(
            entry__source_type="payment", entry__source_id=p.pk, account__code="4110"
        )
        net = sum(line.credit - line.debit for line in lines)
        assert net == Decimal("0.00")

    def test_void_of_deposit_reverses_deposit_accounts_not_income(self, building, coa):
        """The old negative-Payment void dropped payment_type and hit 4110."""
        from apps.ledger.models import JournalLine

        t = _tenant(_unit(building, "R3", Decimal("10000")), Decimal("10000"), "C3C")
        p = process_payment(
            tenant=t, amount=Decimal("15000"), payment_date=PAY_DATE,
            period_month=6, period_year=2026, reference="C3C",
            payment_type=PaymentType.DEPOSIT,
        )
        void_payment(p, reason="wrong tenant")

        reversal_codes = set(
            JournalLine.objects.filter(
                entry__source_type="payment", entry__source_id=p.pk,
                entry__kind="reversal",
            ).values_list("account__code", flat=True)
        )
        assert reversal_codes == {"1030", "2100"}
        assert "4110" not in reversal_codes

    def test_void_restores_the_arrears_balance(self, building, coa):
        t = _tenant(_unit(building, "R4", Decimal("10000")), Decimal("10000"), "C3D")
        _arrear(t, 6, 2026, Decimal("10000"))
        p = process_payment(
            tenant=t, amount=Decimal("10000"), payment_date=PAY_DATE,
            period_month=6, period_year=2026, reference="C3D",
        )
        assert Arrears.objects.get(tenant=t, period_month=6).is_cleared is True

        void_payment(p, reason="bounced")
        ar = Arrears.objects.get(tenant=t, period_month=6)
        assert ar.balance == Decimal("10000.00")
        assert ar.is_cleared is False

    def test_void_is_idempotent(self, building, coa):
        t = _tenant(_unit(building, "R5", Decimal("10000")), Decimal("10000"), "C3E")
        p = process_payment(
            tenant=t, amount=Decimal("10000"), payment_date=PAY_DATE,
            period_month=6, period_year=2026, reference="C3E",
        )
        first = void_payment(p, reason="once").voided_at
        assert void_payment(p, reason="twice").voided_at == first

    def test_voided_payment_leaves_income_reports(self, building, coa):
        api, _ = _client()
        t = _tenant(_unit(building, "R6", Decimal("10000")), Decimal("10000"), "C3F")
        p = process_payment(
            tenant=t, amount=Decimal("10000"), payment_date=PAY_DATE,
            period_month=6, period_year=2026, reference="C3F",
        )
        void_payment(p, reason="reversed by bank")

        body = api.get("/api/reports/monthly-collection/", {"month": 6, "year": 2026}).json()
        assert body["total"] == 0


# ── C4 — only rent settles rent ─────────────────────────────────────────────

class TestC4PaymentTypes:
    @pytest.mark.parametrize("ptype", [PaymentType.DEPOSIT, PaymentType.LATE_FEE, PaymentType.OTHER])
    def test_non_rent_does_not_clear_arrears(self, building, ptype):
        t = _tenant(_unit(building, f"N{ptype}", Decimal("15000")), Decimal("15000"), f"C4{ptype}")
        _arrear(t, 6, 2026, Decimal("15000"))
        process_payment(
            tenant=t, amount=Decimal("15000"), payment_date=PAY_DATE,
            period_month=6, period_year=2026, reference=f"C4-{ptype}",
            payment_type=ptype,
        )
        ar = Arrears.objects.get(tenant=t, period_month=6)
        assert ar.amount_paid == Decimal("0.00")
        assert ar.balance == Decimal("15000.00")
        assert ar.is_cleared is False


# ── C5 / C6 — authorization ─────────────────────────────────────────────────

class TestC5Permissions:
    def _payload(self, tenant):
        return {
            "tenant": tenant.pk, "amount": "10000.00",
            "payment_date": PAY_DATE.isoformat(),
            "period_month": 6, "period_year": 2026, "source": "cash",
        }

    @pytest.mark.parametrize("role,expected", [
        (Role.OWNER, 201), (Role.ACCOUNTANT, 201),
        (Role.CARETAKER, 403), (Role.VIEWER, 403),
    ])
    def test_recording_a_payment_requires_a_money_role(self, building, coa, role, expected):
        api, _ = _client(role)
        t = _tenant(_unit(building, f"P{role}", Decimal("10000")), Decimal("10000"), f"C5{role}")
        resp = api.post("/api/payments/", self._payload(t), format="json")
        assert resp.status_code == expected

    @pytest.mark.parametrize("role,expected", [
        (Role.OWNER, 200), (Role.ACCOUNTANT, 403), (Role.VIEWER, 403),
    ])
    def test_waiving_is_owner_only(self, building, role, expected):
        api, _ = _client(role)
        t = _tenant(_unit(building, f"W{role}", Decimal("10000")), Decimal("10000"), f"C5W{role}")
        ar = _arrear(t, 6, 2026, Decimal("10000"))
        resp = api.post(f"/api/arrears/{ar.pk}/waive/", {"notes": "hardship"}, format="json")
        assert resp.status_code == expected

    @pytest.mark.parametrize("role,expected", [
        (Role.OWNER, 200), (Role.ACCOUNTANT, 403), (Role.VIEWER, 403),
    ])
    def test_voiding_is_owner_only(self, building, coa, role, expected):
        api, _ = _client(role)
        t = _tenant(_unit(building, f"V{role}", Decimal("10000")), Decimal("10000"), f"C5V{role}")
        p = process_payment(
            tenant=t, amount=Decimal("10000"), payment_date=PAY_DATE,
            period_month=6, period_year=2026, reference=f"C5V{role}",
        )
        resp = api.post(f"/api/payments/{p.pk}/void/", {"reason": "error"}, format="json")
        assert resp.status_code == expected

    def test_reading_is_open_to_any_authenticated_user(self, building):
        api, _ = _client(Role.VIEWER)
        assert api.get("/api/payments/").status_code == 200

    def test_unauthenticated_is_rejected(self):
        assert APIClient().get("/api/payments/").status_code == 401

    def test_void_requires_a_reason(self, building, coa):
        api, _ = _client(Role.OWNER)
        t = _tenant(_unit(building, "VR", Decimal("10000")), Decimal("10000"), "C5VR")
        p = process_payment(
            tenant=t, amount=Decimal("10000"), payment_date=PAY_DATE,
            period_month=6, period_year=2026, reference="C5VR",
        )
        assert api.post(f"/api/payments/{p.pk}/void/", {}, format="json").status_code == 400


class TestC6MockEndpoint:
    def test_mock_is_unreachable_when_debug_is_off(self, building, settings):
        settings.DEBUG = False
        api, _ = _client(Role.OWNER)
        t = _tenant(_unit(building, "MK1", Decimal("10000")), Decimal("10000"), "C6A")
        resp = api.post(
            "/api/payments/mock/",
            {"tenant": t.pk, "amount": "500000", "source": "mpesa"}, format="json",
        )
        assert resp.status_code == 404
        assert Payment.objects.filter(tenant=t).count() == 0


# ── H1 — credit carry-forward ───────────────────────────────────────────────

class TestH1Credit:
    def test_overpayment_becomes_available_credit(self, building):
        t = _tenant(_unit(building, "CR1", Decimal("10000")), Decimal("10000"), "H1A")
        _arrear(t, 6, 2026, Decimal("10000"))
        process_payment(
            tenant=t, amount=Decimal("25000"), payment_date=PAY_DATE,
            period_month=6, period_year=2026, reference="H1A",
        )
        assert available_credit(t) == Decimal("15000.00")

    def test_next_period_draws_on_the_credit(self, building):
        from apps.payments.services import apply_available_credit

        t = _tenant(_unit(building, "CR2", Decimal("10000")), Decimal("10000"), "H1B")
        _arrear(t, 6, 2026, Decimal("10000"))
        process_payment(
            tenant=t, amount=Decimal("25000"), payment_date=PAY_DATE,
            period_month=6, period_year=2026, reference="H1B",
        )
        july = _arrear(t, 7, 2026, Decimal("10000"))
        apply_available_credit(july)
        july.refresh_from_db()

        assert july.credit_applied == Decimal("10000.00")
        assert july.balance == Decimal("0.00")
        assert july.is_cleared is True
        # 15,000 banked, 10,000 consumed → 5,000 still available for August.
        assert available_credit(t) == Decimal("5000.00")

    def test_credit_survives_an_arrears_recompute(self, building):
        from apps.payments.services import _update_arrears, apply_available_credit

        t = _tenant(_unit(building, "CR3", Decimal("10000")), Decimal("10000"), "H1C")
        _arrear(t, 6, 2026, Decimal("10000"))
        process_payment(
            tenant=t, amount=Decimal("25000"), payment_date=PAY_DATE,
            period_month=6, period_year=2026, reference="H1C",
        )
        july = _arrear(t, 7, 2026, Decimal("10000"))
        apply_available_credit(july)

        _update_arrears(t, 7, 2026)
        july.refresh_from_db()
        assert july.credit_applied == Decimal("10000.00")
        assert july.is_cleared is True


# ── H2 / H3 — statement ─────────────────────────────────────────────────────

class TestStatementCorrections:
    def test_h2_waiver_is_credited_on_the_statement(self, building):
        from apps.payments.statement_service import build_statement

        t = _tenant(_unit(building, "S1", Decimal("10000")), Decimal("10000"), "H2A")
        ar = _arrear(t, 6, 2026, Decimal("10000"))
        ar.waived_amount = Decimal("10000")
        ar.balance = Decimal("0")
        ar.is_cleared = True
        ar.waive_notes = "fire damage"
        ar.save()

        st = build_statement(t, statement_date=PAY_DATE, as_of=PAY_DATE)
        assert st["total_due_value"] == Decimal("0.00")
        assert any("Waiver" in row["description"] for row in st["rows"])

    def test_h3_deposit_is_not_netted_against_rent(self, building):
        from apps.payments.statement_service import build_statement

        t = _tenant(_unit(building, "S2", Decimal("10000")), Decimal("10000"), "H3A")
        _arrear(t, 6, 2026, Decimal("10000"))
        process_payment(
            tenant=t, amount=Decimal("20000"), payment_date=PAY_DATE,
            period_month=6, period_year=2026, reference="H3A",
            payment_type=PaymentType.DEPOSIT,
        )
        st = build_statement(t, statement_date=PAY_DATE, as_of=PAY_DATE)
        # Rent still owed in full; the deposit shows only on its own line.
        assert st["total_due_value"] == Decimal("10000.00")
        assert st["security_deposit"] == "20,000.00"

    def test_voided_payment_leaves_the_statement(self, building, coa):
        from apps.payments.statement_service import build_statement

        t = _tenant(_unit(building, "S3", Decimal("10000")), Decimal("10000"), "H3B")
        _arrear(t, 6, 2026, Decimal("10000"))
        p = process_payment(
            tenant=t, amount=Decimal("10000"), payment_date=PAY_DATE,
            period_month=6, period_year=2026, reference="H3B",
        )
        void_payment(p, reason="cheque bounced")
        st = build_statement(t, statement_date=PAY_DATE, as_of=PAY_DATE)
        assert st["total_due_value"] == Decimal("10000.00")


# ── H5 — reversal matching ──────────────────────────────────────────────────

class TestH5ReversalMatching:
    def _recorded(self, txn_id, payment_ref=""):
        from apps.payments.models import CoopIpnEvent, CoopIpnStatus

        return CoopIpnEvent.objects.create(
            transaction_id=txn_id, payment_ref=payment_ref, amount=Decimal("1000"),
            event_type="CREDIT", raw_payload={}, status=CoopIpnStatus.RECORDED,
        )

    def test_matches_an_original_older_than_500_events(self, db):
        from apps.payments.coop_ipn import _reversal_check
        from apps.payments.models import CoopIpnEvent, CoopIpnStatus

        target = self._recorded("ORIGINAL123")
        CoopIpnEvent.objects.bulk_create([
            CoopIpnEvent(
                transaction_id=f"NOISE{i:05d}", amount=Decimal("1"), event_type="CREDIT",
                raw_payload={}, status=CoopIpnStatus.RECORDED,
            )
            for i in range(600)
        ])
        is_reversal, original = _reversal_check(
            "DEBIT", "", {"Narration": "REVERSAL OF ORIGINAL123"}
        )
        assert is_reversal is True
        assert original is not None and original.pk == target.pk

    def test_does_not_match_on_a_substring(self, db):
        """A ref embedded inside a longer token is a different reference."""
        from apps.payments.coop_ipn import _reversal_check

        self._recorded("ABC12345")
        is_reversal, original = _reversal_check(
            "DEBIT", "", {"Narration": "PAYMENT XXABC12345YY for goods"}
        )
        assert original is None
        assert is_reversal is False

    def test_credit_events_are_never_reversals(self, db):
        from apps.payments.coop_ipn import _reversal_check

        assert _reversal_check("CREDIT", "REVERSAL", {}) == (False, None)


# ── H7 — audit trail ────────────────────────────────────────────────────────

class TestH7AuditTrail:
    def test_payment_creation_is_attributed(self, building, coa):
        api, user = _client(Role.ACCOUNTANT)
        t = _tenant(_unit(building, "AU1", Decimal("10000")), Decimal("10000"), "H7A")
        api.post("/api/payments/", {
            "tenant": t.pk, "amount": "10000.00", "payment_date": PAY_DATE.isoformat(),
            "period_month": 6, "period_year": 2026, "source": "cash", "reference": "AU1",
        }, format="json")

        payment = Payment.objects.get(tenant=t)
        assert payment.created_by_id == user.pk
        assert FinancialAuditLog.objects.filter(
            action="payment.create", object_id=payment.pk, actor=user
        ).exists()

    def test_waiver_is_attributed_with_the_old_balance(self, building):
        api, user = _client(Role.OWNER)
        t = _tenant(_unit(building, "AU2", Decimal("10000")), Decimal("10000"), "H7B")
        ar = _arrear(t, 6, 2026, Decimal("10000"))
        api.post(f"/api/arrears/{ar.pk}/waive/", {"notes": "goodwill"}, format="json")

        log = FinancialAuditLog.objects.get(action="arrears.waive", object_id=ar.pk)
        assert log.actor_id == user.pk
        assert log.old_values["balance"] == "10000.00"
        assert "goodwill" in log.summary

    def test_void_is_attributed(self, building, coa):
        api, user = _client(Role.OWNER)
        t = _tenant(_unit(building, "AU3", Decimal("10000")), Decimal("10000"), "H7C")
        p = process_payment(
            tenant=t, amount=Decimal("10000"), payment_date=PAY_DATE,
            period_month=6, period_year=2026, reference="AU3",
        )
        api.post(f"/api/payments/{p.pk}/void/", {"reason": "keyed twice"}, format="json")

        log = FinancialAuditLog.objects.get(action="payment.void", object_id=p.pk)
        assert log.actor_id == user.pk
        assert "keyed twice" in log.summary
        p.refresh_from_db()
        assert p.voided_by_id == user.pk
