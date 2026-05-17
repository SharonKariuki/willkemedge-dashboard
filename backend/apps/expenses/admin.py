from django.contrib import admin

from .models import Account, Expense, ExpenseCategory


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "account_type", "is_active"]
    list_filter = ["account_type", "is_active"]
    search_fields = ["code", "name"]
    ordering = ["code"]


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "account", "description", "created_at"]
    list_filter = ["account"]
    search_fields = ["name"]
    autocomplete_fields = ["account"]


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ["date", "building", "category", "amount", "description", "period_month", "period_year", "reference"]
    list_filter = ["building", "category", "period_year", "period_month"]
    search_fields = ["description", "reference"]
    ordering = ["-date"]
