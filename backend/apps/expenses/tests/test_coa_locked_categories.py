"""
Tests for COA-locked expense categories (Barclay F5).

Acceptance criteria:
  - the category dropdown maps each option to a fixed GL code from the COA
  - free-text / ad-hoc GL entry is not permitted
  - existing expenses without a code are flagged for review
  - all entries reconcile against COA codes
"""
from decimal import Decimal
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.expenses.coa import EXPENSE_CATEGORIES
from apps.expenses.models import Account, Expense, ExpenseCategory

User = get_user_model()


@pytest.fixture
def client(db):
    user = User.objects.create_user(username="admin", email="a@t.com", password="pw123456!")
    c = APIClient()
    c.force_authenticate(user=user)
    return c


@pytest.mark.django_db
class TestCategoriesAreLocked:
    def test_seed_creates_every_category_bound_to_a_gl_code(self):
        call_command("seed_coa", stdout=StringIO())
        for name, code in EXPENSE_CATEGORIES:
            cat = ExpenseCategory.objects.get(name=name)
            assert cat.account is not None
            assert cat.account.code == code

    def test_seed_repairs_a_legacy_uncoded_category(self):
        ExpenseCategory.objects.update_or_create(name="repairs", defaults={"account": None})
        call_command("seed_coa", stdout=StringIO())
        cat = ExpenseCategory.objects.get(name="repairs")
        assert cat.account is not None
        assert cat.account.code == "5200"

    def test_category_api_is_read_only(self, client):
        """Ad-hoc categories (which could carry no GL code) cannot be created."""
        resp = client.post(
            "/api/expenses/categories/",
            {"name": "Made Up", "account": None},
            format="json",
        )
        assert resp.status_code == 405  # Method Not Allowed
        assert not ExpenseCategory.objects.filter(name="Made Up").exists()

    def test_every_seeded_category_maps_to_an_expense_account(self):
        call_command("seed_coa", stdout=StringIO())
        for cat in ExpenseCategory.objects.exclude(account__isnull=True):
            assert cat.account.account_type == "expense"
            assert cat.account.is_header is False


@pytest.mark.django_db
class TestExpensesReconcileToCoa:
    def test_expense_under_uncoded_category_is_rejected(self, client):
        orphan = ExpenseCategory.objects.create(name="No GL Code", account=None)
        resp = client.post(
            "/api/expenses/",
            {
                "date": "2026-06-10", "category": orphan.id, "amount": "500.00",
                "description": "Test", "period_month": 6, "period_year": 2026,
            },
            format="json",
        )
        assert resp.status_code == 400
        assert "no GL account" in str(resp.json())
        assert not Expense.objects.filter(category=orphan).exists()

    def test_expense_under_coded_category_is_accepted(self, client):
        call_command("seed_coa", stdout=StringIO())
        cat = ExpenseCategory.objects.get(name="Repairs & Maintenance")
        resp = client.post(
            "/api/expenses/",
            {
                "date": "2026-06-10", "category": cat.id, "amount": "500.00",
                "description": "Fix tap", "period_month": 6, "period_year": 2026,
            },
            format="json",
        )
        assert resp.status_code == 201
        expense = Expense.objects.get(pk=resp.json()["id"])
        assert expense.category.account.code == "5200"


@pytest.mark.django_db
class TestAuditFlagsUncoded:
    def test_audit_reports_uncoded_category_and_its_expenses(self):
        orphan = ExpenseCategory.objects.create(name="Orphan Cat", account=None)
        Expense.objects.create(
            date="2026-06-10", category=orphan, amount=Decimal("100"),
            description="legacy", period_month=6, period_year=2026,
        )
        out = StringIO()
        call_command("seed_coa", "--audit", stdout=out)
        report = out.getvalue()
        assert "Orphan Cat" in report
        assert "SKIPPED by the ledger" in report

    def test_chart_accounts_all_present_after_seed(self):
        call_command("seed_coa", stdout=StringIO())
        assert Account.objects.filter(code="5200").exists()
        assert Account.objects.filter(code="2600").exists()
