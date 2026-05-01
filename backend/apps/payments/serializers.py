"""Payment serializers."""
from rest_framework import serializers

from .models import Arrears, Payment, Transaction


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


# ---------------------------------------------------------------------------
# Transaction serializers
# ---------------------------------------------------------------------------

class TransactionSerializer(serializers.ModelSerializer):
    """Full transaction record — all stored values, never recomputed."""

    tenant_name = serializers.CharField(source="tenant.full_name", read_only=True)
    unit_label = serializers.CharField(source="tenant.unit.label", read_only=True)
    building_name = serializers.CharField(source="tenant.unit.building.name", read_only=True)
    unit_classification_display = serializers.CharField(
        source="get_unit_classification_display", read_only=True
    )
    payment_mode_display = serializers.CharField(
        source="get_payment_mode_display", read_only=True
    )

    class Meta:
        model = Transaction
        fields = [
            "id",
            "transaction_id",
            "tenant",
            "tenant_name",
            "unit_label",
            "building_name",
            "unit_classification",
            "unit_classification_display",
            "base_amount",
            "tax_amount",
            "total_amount",
            "payment_mode",
            "payment_mode_display",
            "reference_code",
            "created_at",
        ]
        read_only_fields = fields


class ReceiptSerializer(serializers.Serializer):
    """
    Receipt data shape returned by GET /api/payments/transactions/{id}/receipt/.

    Mirrors ReceiptData from receipt_service.py.
    Conditional fields use SerializerMethodField so falsy values render
    explicitly as null rather than being silently omitted.
    """

    transaction_id = serializers.CharField()
    reference_code = serializers.CharField()
    payment_mode = serializers.CharField()

    tenant_name = serializers.CharField()
    unit_label = serializers.CharField()
    building_name = serializers.CharField()
    period_month = serializers.IntegerField()
    period_year = serializers.IntegerField()
    payment_date = serializers.CharField(allow_null=True)

    unit_classification = serializers.CharField()
    base_amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    tax_amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_amount = serializers.DecimalField(max_digits=10, decimal_places=2)

    # Conditional rendering flags
    show_tax_line = serializers.BooleanField()
    show_total_only = serializers.BooleanField()

    # Optional fields
    outstanding_balance = serializers.DecimalField(
        max_digits=10, decimal_places=2, allow_null=True
    )
