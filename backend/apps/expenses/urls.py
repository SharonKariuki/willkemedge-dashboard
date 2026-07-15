"""Expense URL routes."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AccountViewSet,
    ExpenseCategoryViewSet,
    ExpenseViewSet,
    ManualIncomeViewSet,
)

router = DefaultRouter()
router.register("accounting/accounts", AccountViewSet, basename="account")
router.register("expenses/categories", ExpenseCategoryViewSet, basename="expense-category")
router.register("expenses", ExpenseViewSet, basename="expense")
router.register("manual-income", ManualIncomeViewSet, basename="manual-income")

app_name = "expenses"

urlpatterns = [
    path("", include(router.urls)),
]
