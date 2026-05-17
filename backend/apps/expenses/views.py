"""Expense API views."""
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from .models import Account, Expense, ExpenseCategory
from .serializers import AccountSerializer, ExpenseCategorySerializer, ExpenseSerializer


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


class ExpenseCategoryViewSet(viewsets.ModelViewSet):
    """CRUD for expense categories."""

    queryset = ExpenseCategory.objects.select_related("account").all()
    serializer_class = ExpenseCategorySerializer
    permission_classes = [IsAuthenticated]


class ExpenseViewSet(viewsets.ModelViewSet):
    """
    CRUD for expenses.
    Supports filtering by ?month=&year= and ?category=
    """

    serializer_class = ExpenseSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Expense.objects.select_related("category", "building")

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

        return qs
