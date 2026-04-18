"""Expense serializers."""
from rest_framework import serializers

from .models import Expense, ExpenseCategory


class ExpenseCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseCategory
        fields = ["id", "name", "description", "created_at"]
        read_only_fields = ["id", "created_at"]


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

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Amount must be positive.")
        return value
