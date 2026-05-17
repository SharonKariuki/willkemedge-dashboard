"""Expense serializers."""
from rest_framework import serializers

from .models import Account, Expense, ExpenseCategory


class AccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = Account
        fields = ["id", "code", "name", "account_type", "description", "is_active"]
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
