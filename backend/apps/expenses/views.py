"""Expense API views."""
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from .models import Expense, ExpenseCategory
from .serializers import ExpenseCategorySerializer, ExpenseSerializer


class ExpenseCategoryViewSet(viewsets.ModelViewSet):
    """CRUD for expense categories."""

    queryset = ExpenseCategory.objects.all()
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
        qs = Expense.objects.select_related("category")

        month = self.request.query_params.get("month")
        year = self.request.query_params.get("year")
        if month and year:
            qs = qs.filter(period_month=month, period_year=year)

        category = self.request.query_params.get("category")
        if category:
            qs = qs.filter(category_id=category)

        return qs
