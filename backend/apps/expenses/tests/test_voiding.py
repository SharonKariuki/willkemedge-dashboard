"""
Expenses and other income are voided, not deleted.

A void keeps the row with who voided it, when and why; the ledger keeps the
original entry and gains its reversal; totals and the books leave it out.
Signed in with real tokens so the access policy applies.
"""
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import AuditLog, User
from apps.buildings.models import Building, MaintenanceRequest, PropertyType, Unit, UnitStatus
from apps.expenses.models import Account, Expense, ExpenseCategory, ManualIncome
from apps.ledger import checks
from apps.ledger.models import JournalEntry
from apps.ledger.rebuild import rebuild


def _client(user):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return c


@pytest.fixture
def owner(db):
    return User.objects.create_user(
        username="owner@w.test", email="owner@w.test", password="pw-123456!", role="owner"
    )


@pytest.fixture
def building(db):
    return Building.objects.create(name="Block A", total_floors=1)


@pytest.fixture
def expense(owner, building):
    category = ExpenseCategory.objects.create(name="Plumbing", account=Account.objects.get(code="5200"))
    resp = _client(owner).post("/api/expenses/", {
        "date": "2026-10-03", "building": building.id, "category": category.id,
        "amount": "4500.00", "description": "Tap repair",
        "period_month": 10, "period_year": 2026,
    }, format="json")
    assert resp.status_code == 201, resp.json()
    return Expense.objects.get(pk=resp.json()["id"])


@pytest.fixture
def income(owner):
    farm = Building.objects.create(
        name="Farm", code="FS", property_type=PropertyType.FARM, total_floors=1,
    )
    resp = _client(owner).post("/api/manual-income/", {
        "date": "2026-10-03", "building": farm.id, "account": Account.objects.get(code="4150").id,
        "amount": "12000.00", "description": "Maize sale",
        "period_month": 10, "period_year": 2026,
    }, format="json")
    assert resp.status_code == 201, resp.json()
    return ManualIncome.objects.get(pk=resp.json()["id"])


def _entries(source_type, pk):
    return dict(
        JournalEntry.objects.filter(source_type=source_type, source_id=pk)
        .values_list("kind", "id")
    )


@pytest.mark.django_db
class TestVoidingAnExpense:
    def test_delete_is_refused(self, owner, expense):
        assert _client(owner).delete(f"/api/expenses/{expense.pk}/").status_code == 405
        assert Expense.objects.filter(pk=expense.pk).exists()

    def test_a_reason_is_required(self, owner, expense):
        resp = _client(owner).post(f"/api/expenses/{expense.pk}/void/", {"reason": "  "}, format="json")
        assert resp.status_code == 400
        assert not Expense.objects.get(pk=expense.pk).is_void

    def test_void_keeps_the_row_and_reverses_the_ledger(self, owner, expense):
        resp = _client(owner).post(
            f"/api/expenses/{expense.pk}/void/", {"reason": "Entered twice"}, format="json"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_void"] is True
        assert body["void_reason"] == "Entered twice"
        assert body["voided_by_name"]
        assert set(_entries("expense", expense.pk)) == {"normal", "reversal"}

    def test_voided_expense_is_listed_but_marked_and_can_be_left_out(self, owner, expense):
        c = _client(owner)
        c.post(f"/api/expenses/{expense.pk}/void/", {"reason": "Wrong property"}, format="json")
        listed = c.get("/api/expenses/").json()
        assert [e["is_void"] for e in listed] == [True]
        assert c.get("/api/expenses/", {"active": "1"}).json() == []

    def test_cannot_void_twice_or_edit_a_void(self, owner, expense):
        c = _client(owner)
        c.post(f"/api/expenses/{expense.pk}/void/", {"reason": "Wrong"}, format="json")
        again = c.post(f"/api/expenses/{expense.pk}/void/", {"reason": "Again"}, format="json")
        assert again.status_code == 400
        edit = c.patch(f"/api/expenses/{expense.pk}/", {"amount": "1.00"}, format="json")
        assert edit.status_code == 400
        assert JournalEntry.objects.filter(
            source_type="expense", source_id=expense.pk, kind="reversal"
        ).count() == 1

    def test_void_is_in_the_activity_log_and_flags_your_own_entry(self, owner, expense):
        _client(owner).post(f"/api/expenses/{expense.pk}/void/", {"reason": "Mine"}, format="json")
        row = AuditLog.objects.get(action="expense.void", object_id=expense.pk)
        assert row.actor_id == owner.pk
        assert "Mine" in row.summary
        # The owner recorded it through the API, so undoing it is their own entry.
        assert row.new_values.get("self_reversal") is True

    def test_a_maintenance_cost_is_voided_from_its_request_not_here(self, owner, building):
        call_command("seed_coa", stdout=StringIO())
        unit = Unit.objects.create(
            building=building, label="A1", monthly_rent=Decimal("10000"), status=UnitStatus.VACANT,
        )
        resp = _client(owner).post("/api/maintenance/", {
            "unit": unit.id, "description": "Replace tap", "cost": "3500.00",
            "reported_date": "2026-10-03", "status": "open",
        }, format="json")
        assert resp.status_code == 201, resp.json()
        expense = MaintenanceRequest.objects.get(pk=resp.json()["id"]).expense
        void = _client(owner).post(f"/api/expenses/{expense.pk}/void/", {"reason": "x"}, format="json")
        assert void.status_code == 400
        assert "maintenance request" in void.json()["detail"]

    def test_read_only_people_cannot_void(self, expense):
        viewer = User.objects.create_user(
            username="v@w.test", email="v@w.test", password="pw-123456!", role="viewer"
        )
        resp = _client(viewer).post(f"/api/expenses/{expense.pk}/void/", {"reason": "x"}, format="json")
        assert resp.status_code == 403
        assert not Expense.objects.get(pk=expense.pk).is_void

    def test_the_books_stay_complete_and_a_rebuild_keeps_the_reversal(self, owner, expense):
        _client(owner).post(f"/api/expenses/{expense.pk}/void/", {"reason": "Wrong"}, format="json")
        assert checks._check_complete().ok
        rebuild()
        assert set(_entries("expense", expense.pk)) == {"normal", "reversal"}


@pytest.mark.django_db
class TestVoidingIncome:
    def test_void_reverses_and_delete_is_refused(self, owner, income):
        c = _client(owner)
        assert c.delete(f"/api/manual-income/{income.pk}/").status_code == 405
        resp = c.post(f"/api/manual-income/{income.pk}/void/", {"reason": "Not ours"}, format="json")
        assert resp.status_code == 200
        assert resp.json()["is_void"] is True
        assert set(_entries("manual_income", income.pk)) == {"normal", "reversal"}
        assert checks._check_complete().ok
