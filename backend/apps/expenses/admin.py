from django.contrib import admin

from .models import Expense, ExpenseCategory


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "description", "created_at"]
    search_fields = ["name"]


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ["date", "building", "category", "amount", "description", "period_month", "period_year", "reference"]
    list_filter = ["building", "category", "period_year", "period_month"]
    search_fields = ["description", "reference"]
    ordering = ["-date"]
