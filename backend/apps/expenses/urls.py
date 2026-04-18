"""Expense URL routes."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import ExpenseCategoryViewSet, ExpenseViewSet

router = DefaultRouter()
router.register("expenses/categories", ExpenseCategoryViewSet, basename="expense-category")
router.register("expenses", ExpenseViewSet, basename="expense")

app_name = "expenses"

urlpatterns = [
    path("", include(router.urls)),
]
