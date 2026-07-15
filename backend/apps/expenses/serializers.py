"""Expense serializers."""
from rest_framework import serializers

from .models import Account, Expense, ExpenseCategory, ManualIncome


class AccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = Account
        fields = ["id", "code", "name", "account_type", "parent_code", "is_header", "description", "is_active"]
        read_only_fields = ["id"]


class ExpenseCategorySerializer(serializers.ModelSerializer):
    account_code = serializers.CharField(source="account.code", read_only=True, default=None)
    account_name = serializers.CharField(source="account.name", read_only=True, default=None)

    class Meta:
        model = ExpenseCategory
        fields = [
            "id", "name", "description",
            "account", "account_code", "account_name",
            "created_at",
        ]
        read_only_fields = ["id", "account_code", "account_name", "created_at"]


class ExpenseSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    building_name = serializers.CharField(source="building.name", read_only=True, default=None)

    class Meta:
        model = Expense
        fields = [
            "id",
            "date",
            "building",
            "building_name",
            "category",
            "category_name",
            "amount",
            "description",
            "reference",
            "period_month",
            "period_year",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "category_name", "building_name", "created_at", "updated_at"]

    def validate_period_month(self, value):
        if not 1 <= value <= 12:
            raise serializers.ValidationError("Month must be between 1 and 12.")
        return value

    def validate_period_year(self, value):
        if not 2020 <= value <= 2100:
            raise serializers.ValidationError("Year must be between 2020 and 2100.")
        return value

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Amount must be positive.")
        return value

    def validate_category(self, category):
        """Every expense must reconcile to a COA code.

        A category with no GL account is skipped by the ledger posting signal,
        so the expense would never appear in the general ledger. Reject it at
        the door rather than losing it silently.
        """
        if category.account_id is None:
            raise serializers.ValidationError(
                f"Category '{category.name}' has no GL account. "
                f"Run `manage.py seed_coa` to bind it to a Chart of Accounts code."
            )
        return category


class ManualIncomeSerializer(serializers.ModelSerializer):
    building_name = serializers.CharField(source="building.name", read_only=True)
    account_code = serializers.CharField(source="account.code", read_only=True)
    account_name = serializers.CharField(source="account.name", read_only=True)

    class Meta:
        model = ManualIncome
        fields = [
            "id", "date", "building", "building_name",
            "account", "account_code", "account_name",
            "amount", "description", "reference",
            "period_month", "period_year", "notes",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "building_name", "account_code", "account_name",
                            "created_at", "updated_at"]

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Amount must be positive.")
        return value

    def validate_building(self, building):
        # Baobab Karen (KRN) and any expense-only property may not record income.
        if not building.allows_income:
            raise serializers.ValidationError(
                f"{building.name} is an expenses-only property — income cannot be recorded here."
            )
        return building
