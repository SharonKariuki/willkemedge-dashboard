"""Payment serializers."""
from rest_framework import serializers

from .models import Arrears, Payment


class PaymentSerializer(serializers.ModelSerializer):
    tenant_name = serializers.CharField(source="tenant.full_name", read_only=True)
    unit_label = serializers.CharField(source="tenant.unit.label", read_only=True)
    building_name = serializers.CharField(source="tenant.unit.building.name", read_only=True)
    source_display = serializers.CharField(source="get_source_display", read_only=True)

    class Meta:
        model = Payment
        fields = [
            "id",
            "tenant",
            "tenant_name",
            "unit_label",
            "building_name",
            "amount",
            "payment_date",
            "period_month",
            "period_year",
            "source",
            "source_display",
            "reference",
            "notes",
            "created_at",
        ]


class PaymentCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = [
            "tenant",
            "amount",
            "payment_date",
            "period_month",
            "period_year",
            "source",
            "reference",
            "notes",
        ]

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Amount must be positive.")
        return value

    def validate_period_month(self, value):
        if not 1 <= value <= 12:
            raise serializers.ValidationError("Month must be between 1 and 12.")
        return value


class ArrearsSerializer(serializers.ModelSerializer):
    tenant_name = serializers.CharField(source="tenant.full_name", read_only=True)
    unit_label = serializers.CharField(source="tenant.unit.label", read_only=True)

    class Meta:
        model = Arrears
        fields = [
            "id",
            "tenant",
            "tenant_name",
            "unit_label",
            "period_month",
            "period_year",
            "expected_rent",
            "amount_paid",
            "balance",
            "is_cleared",
            "updated_at",
        ]


class CollectionProgressSerializer(serializers.Serializer):
    expected = serializers.DecimalField(max_digits=12, decimal_places=2)
    collected = serializers.DecimalField(max_digits=12, decimal_places=2)
    percentage = serializers.DecimalField(max_digits=5, decimal_places=1)
    period_month = serializers.IntegerField()
    period_year = serializers.IntegerField()
