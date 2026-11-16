"""Expense API views."""
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Account, Expense, ExpenseCategory, ManualIncome
from .serializers import (
    AccountSerializer,
    ExpenseCategorySerializer,
    ExpenseSerializer,
    ManualIncomeSerializer,
)
from .voiding import void_entry


class VoidInsteadOfDelete:
    """Entries are voided with a reason, not deleted (see ``voiding.py``).

    Lists include voided rows, marked ``is_void``, so the page can show them
    struck through; ``?active=1`` leaves them out.
    """

    http_method_names = ["get", "post", "put", "patch", "head", "options"]

    def filter_voided(self, qs):
        if self.request.query_params.get("active") in ("1", "true"):
            qs = qs.filter(voided_at__isnull=True)
        return qs.select_related("voided_by")

    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        entry = void_entry(
            self.get_object(), user=request.user, reason=request.data.get("reason", "")
        )
        return Response(self.get_serializer(entry).data)


class AccountViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only Chart of Accounts. Filter by ?type=expense|income|asset|liability|equity."""

    serializer_class = AccountSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Account.objects.filter(is_active=True)
        account_type = self.request.query_params.get("type")
        if account_type:
            qs = qs.filter(account_type=account_type)
        return qs


class ExpenseCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only, COA-locked expense categories.

    The category list is the fixed dropdown staff choose from, and each option
    is bound to one GL code from the Chart of Accounts (see ``coa.py``). It is
    deliberately NOT writable over the API: allowing ad-hoc categories let a
    caller create one with no account, and expenses booked under it were then
    silently dropped by the ledger. Categories change via ``seed_coa``.
    """

    queryset = ExpenseCategory.objects.select_related("account").all()
    serializer_class = ExpenseCategorySerializer
    permission_classes = [IsAuthenticated]


class ExpenseViewSet(VoidInsteadOfDelete, viewsets.ModelViewSet):
    """
    CRUD for expenses.

    Filters: ?month=&year=, ?category=, ?building= (or ``none`` for
    portfolio-wide costs) and ?unit= (or ``none`` for costs booked to the
    building as a whole rather than to one unit).
    """

    serializer_class = ExpenseSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Expense.objects.select_related("category", "building", "unit")

        month = self.request.query_params.get("month")
        year = self.request.query_params.get("year")
        if month and year:
            qs = qs.filter(period_month=month, period_year=year)

        category = self.request.query_params.get("category")
        if category:
            qs = qs.filter(category_id=category)

        building = self.request.query_params.get("building")
        if building == "none":
            qs = qs.filter(building__isnull=True)
        elif building:
            qs = qs.filter(building_id=building)

        unit = self.request.query_params.get("unit")
        if unit == "none":
            # Building-wide costs: everything not pinned to a single unit.
            qs = qs.filter(unit__isnull=True)
        elif unit:
            qs = qs.filter(unit_id=unit)

        return self.filter_voided(qs)


class ManualIncomeViewSet(VoidInsteadOfDelete, viewsets.ModelViewSet):
    """Non-tenant income (e.g. farm produce). Posts to the ledger on create.

    Income is rejected for expense-only properties (Baobab Karen / KRN) in the
    serializer, so the 'expenses only' rule is enforced server-side.
    """

    serializer_class = ManualIncomeSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = ManualIncome.objects.select_related("building", "account")
        month = self.request.query_params.get("month")
        year = self.request.query_params.get("year")
        if month and year:
            qs = qs.filter(period_month=month, period_year=year)
        building = self.request.query_params.get("building")
        if building:
            qs = qs.filter(building_id=building)
        return self.filter_voided(qs)
