"""Charges added by hand: a debit that is not rent, booked where it belongs.

Before this, the only way to bill a tenant for anything but rent was a
UtilityCharge made in the Django admin, and every one of them was booked to
4150 Utilities Reimbursed — a broken-window recharge or a late penalty read as
recovered water on the P&L. Each charge now carries a type, and the type picks
an account that is already in the auditor-locked chart.
"""
import datetime as _dt
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.db.models import Sum
from rest_framework.test import APIClient

from apps.accounts.models import AuditLog
from apps.buildings.models import Building, Unit, UnitStatus
from apps.expenses.models import Account, ExpenseCategory
from apps.ledger.models import JournalEntry, JournalLine
from apps.payments import charges, credits
from apps.payments.charges import ChargeError
from apps.payments.models import ChargeType, CreditReason, UtilityCharge
from apps.payments.monthly_ledger import current_balance
from apps.payments.statement_service import build_statement
from apps.tenants.models import Tenant, TenantStatus

D = Decimal
User = get_user_model()

TODAY = _dt.date(2026, 10, 12)
ON = _dt.date(2026, 10, 10)


def _net(code: str) -> Decimal:
    """Debits less credits on one GL account."""
    agg = JournalLine.objects.filter(account__code=code).aggregate(d=Sum("debit"), c=Sum("credit"))
    return (agg["d"] or D("0")) - (agg["c"] or D("0"))


@pytest.fixture
def owner(db):
    return User.objects.create_user(
        username="osoro", email="osoro@test.com", password="pass12345!", role="owner",
    )


@pytest.fixture
def tenant(db):
    building = Building.objects.create(
        name="Donholm", code="DON", total_floors=1, water_rate_per_unit=D("150.00"),
    )
    unit = Unit.objects.create(
        building=building, label="DON1A", monthly_rent=D("12000"),
        status=UnitStatus.OCCUPIED_UNPAID,
    )
    return Tenant.objects.create(
        first_name="Mercy", last_name="Murunga", id_number="M1",
        phone="+254700000001", unit=unit, monthly_rent=D("12000"),
        move_in_date="2026-01-01", status=TenantStatus.ACTIVE,
    )


@pytest.fixture
def repairs(db):
    account = Account.objects.get(code="5200")
    category, _ = ExpenseCategory.objects.get_or_create(
        name="Repairs & Maintenance", defaults={"account": account},
    )
    if category.account_id != account.pk:
        category.account = account
        category.save()
    return category


def _add(tenant, charge_type=ChargeType.LATE_FEE, amount="1500", label="Late payment penalty",
         **kwargs):
    kwargs.setdefault("posting_date", ON)
    kwargs.setdefault("period_month", 10)
    kwargs.setdefault("period_year", 2026)
    kwargs.setdefault("today", TODAY)
    return charges.add_charge(
        tenant=tenant, charge_type=charge_type, amount=amount, label=label, **kwargs,
    )


@pytest.mark.django_db
class TestEachTypeBooksToItsOwnAccount:
    @pytest.mark.parametrize("charge_type, code", [
        (ChargeType.UTILITY, "4150"),
        (ChargeType.ELECTRICITY, "4150"),
        (ChargeType.GARBAGE, "4150"),
        (ChargeType.SECURITY, "4150"),
        (ChargeType.SERVICE_CHARGE, "4150"),
        (ChargeType.LATE_FEE, "4200"),
        (ChargeType.PARKING, "4250"),
    ])
    def test_income_types(self, tenant, charge_type, code):
        _add(tenant, charge_type=charge_type, amount="2000", label="Charge")

        assert _net("1040") == D("2000.00")
        assert _net(code) == D("-2000.00")
        # Nothing strays into the water account unless it is water.
        if code != "4150":
            assert _net("4150") == D("0")

    def test_damage_recharge_credits_the_expense_it_recovers(self, tenant, repairs):
        _add(tenant, charge_type=ChargeType.DAMAGE, amount="3500",
             label="Broken window", expense_category=repairs)

        assert _net("1040") == D("3500.00")
        assert _net("5200") == D("-3500.00")
        assert _net("4150") == D("0")

    def test_a_meter_reading_is_still_a_utility(self, tenant, owner):
        client = APIClient()
        client.force_authenticate(owner)
        resp = client.post("/api/utility-charges/reading/", {
            "tenant": tenant.id, "period_month": 1, "period_year": 2026,
            "opening_reading": "100", "closing_reading": "110",
        }, format="json")
        assert resp.status_code == 201
        assert UtilityCharge.objects.get().charge_type == ChargeType.UTILITY
        assert _net("4150") == D("-1500.00")


@pytest.mark.django_db
class TestTheTenantSeesIt:
    def test_on_the_balance_and_the_statement(self, tenant):
        _add(tenant, amount="1500", label="Late payment penalty")

        assert current_balance(tenant, today=TODAY) == D("1500.00")
        st = build_statement(tenant, statement_date=TODAY, as_of=TODAY)
        assert st["other_charges"] == "1,500.00"
        assert any("Late payment penalty" in r["description_lines"][0] for r in st["rows"])

    def test_a_moved_out_tenant_can_be_recharged(self, tenant, repairs):
        tenant.status = TenantStatus.MOVED_OUT
        tenant.save()
        _add(tenant, charge_type=ChargeType.DAMAGE, amount="800",
             label="Lost keys", expense_category=repairs)
        assert current_balance(tenant, today=TODAY) == D("800.00")


@pytest.mark.django_db
class TestCorrectionsUnwindTheSameAccount:
    def test_credit_note_against_a_penalty_reverses_4200(self, tenant, owner):
        charge = _add(tenant, amount="1500")
        credits.issue_credit(
            tenant=tenant, reason=CreditReason.BILLING_CORRECTION, net_amount="1500",
            credit_date=TODAY, description="Penalty waived", utility_charge=charge,
            actor=owner, today=TODAY,
        )
        assert _net("4200") == D("0")
        assert _net("4150") == D("0")
        assert _net("1040") == D("0")

    def test_deleting_a_recharge_reverses_the_expense(self, tenant, repairs):
        charge = _add(tenant, charge_type=ChargeType.DAMAGE, amount="3500",
                      label="Broken window", expense_category=repairs)
        charge.delete()
        assert _net("5200") == D("0")
        assert _net("1040") == D("0")


@pytest.mark.django_db
class TestRefusals:
    def test_damage_needs_an_expense(self, tenant):
        with pytest.raises(ChargeError, match="expense"):
            _add(tenant, charge_type=ChargeType.DAMAGE, label="Broken window")

    def test_only_damage_takes_an_expense(self, tenant, repairs):
        with pytest.raises(ChargeError, match="only applies"):
            _add(tenant, charge_type=ChargeType.PARKING, label="Parking", expense_category=repairs)

    @pytest.mark.parametrize("amount", ["0", "-100"])
    def test_amount_must_be_positive(self, tenant, amount):
        with pytest.raises(ChargeError, match="greater than 0"):
            _add(tenant, amount=amount)

    def test_no_future_dates(self, tenant):
        with pytest.raises(ChargeError, match="future"):
            _add(tenant, posting_date=TODAY + _dt.timedelta(days=1))

    def test_next_month_is_allowed_but_not_beyond(self, tenant):
        _add(tenant, period_month=11)
        with pytest.raises(ChargeError, match="next month"):
            _add(tenant, period_month=12, label="Later")

    def test_archived_tenants_take_no_charges(self, tenant):
        tenant.status = TenantStatus.ARCHIVED
        tenant.save()
        with pytest.raises(ChargeError, match="archived"):
            _add(tenant)

    @pytest.mark.parametrize("label", ["Water Usage", "water usage"])
    def test_water_usage_belongs_to_the_meter(self, tenant, label):
        with pytest.raises(ChargeError, match="meter readings"):
            _add(tenant, charge_type=ChargeType.UTILITY, label=label)

    def test_any_metered_label_on_the_unit_is_refused(self, tenant):
        UtilityCharge.objects.create(
            tenant=tenant, label="Electricity", posting_date=ON, period_month=9,
            period_year=2026, opening_reading=D("10"), closing_reading=D("20"),
            units=D("10"), amount=D("300"),
        )
        with pytest.raises(ChargeError, match="meter readings"):
            _add(tenant, charge_type=ChargeType.UTILITY, label="Electricity")

    def test_a_double_submit_is_caught(self, tenant):
        _add(tenant)
        with pytest.raises(ChargeError, match="just added"):
            _add(tenant)
        assert UtilityCharge.objects.count() == 1

    def test_nothing_is_kept_when_the_books_refuse_it(self, tenant, monkeypatch):
        def refuse(*args, **kwargs):
            raise ValueError("ledger down")

        monkeypatch.setattr("apps.ledger.posting.post_utility_charge", refuse)
        with pytest.raises(ChargeError, match="could not be booked"):
            _add(tenant)
        assert not UtilityCharge.objects.exists()
        assert not JournalEntry.objects.filter(source_type="utility_charge").exists()


@pytest.mark.django_db
class TestApi:
    def _client(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def _body(self, tenant, **overrides):
        body = {
            "tenant": tenant.id, "charge_type": "late_fee", "amount": "1500",
            "label": "Late payment penalty", "posting_date": str(_dt.date.today()),
            "period_month": _dt.date.today().month, "period_year": _dt.date.today().year,
            "notes": "Paid on the 20th",
        }
        body.update(overrides)
        return body

    def test_owner_adds_a_charge_and_it_is_audited(self, tenant, owner):
        resp = self._client(owner).post("/api/utility-charges/", self._body(tenant), format="json")

        assert resp.status_code == 201, resp.content
        body = resp.json()
        assert body["charge_type"] == "late_fee"
        assert body["charge_type_display"] == "Late payment penalty"
        charge = UtilityCharge.objects.get()
        assert charge.created_by == owner
        assert AuditLog.objects.filter(action="charge.add", object_id=charge.pk).exists()

    def test_an_accountant_cannot(self, tenant):
        clerk = User.objects.create_user(
            username="clerk", email="clerk@test.com", password="pass12345!", role="accountant",
        )
        resp = self._client(clerk).post("/api/utility-charges/", self._body(tenant), format="json")
        assert resp.status_code == 403
        assert not UtilityCharge.objects.exists()

    def test_a_refusal_comes_back_as_a_message(self, tenant, owner):
        resp = self._client(owner).post(
            "/api/utility-charges/", self._body(tenant, charge_type="damage"), format="json",
        )
        assert resp.status_code == 400
        assert "expense" in resp.json()["detail"]

    def test_options_name_the_account_for_each_type(self, owner, repairs):
        resp = self._client(owner).get("/api/utility-charges/options/")

        assert resp.status_code == 200
        types = {t["value"]: t for t in resp.json()["charge_types"]}
        assert types["late_fee"]["account"].startswith("4200")
        assert types["parking"]["account"].startswith("4250")
        for named in ("utility", "electricity", "garbage", "security", "service_charge"):
            assert types[named]["account"].startswith("4150")
        assert types["damage"]["account"] == ""
        assert any(c["id"] == repairs.pk for c in resp.json()["expense_categories"])
