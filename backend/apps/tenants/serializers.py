"""Tenant serializers — updated with deposit refund, notice, and edit fields."""
from rest_framework import serializers

from .models import DocumentType, Tenant, TenantDocument


class TenantDocumentSerializer(serializers.ModelSerializer):
    doc_type_display = serializers.CharField(source="get_doc_type_display", read_only=True)

    class Meta:
        model = TenantDocument
        fields = ["id", "tenant", "doc_type", "doc_type_display", "file", "original_name", "uploaded_at"]
        read_only_fields = ["tenant", "original_name", "uploaded_at"]


class TenantListSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    unit_label = serializers.CharField(source="unit.label", read_only=True)
    building_name = serializers.CharField(source="unit.building.name", read_only=True)
    building_id = serializers.IntegerField(source="unit.building.id", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Tenant
        fields = [
            "id", "full_name", "first_name", "last_name", "phone",
            "unit", "unit_label", "building_name", "building_id",
            "monthly_rent", "deposit_paid", "due_day", "status", "status_display",
            "move_in_date", "move_out_date", "notice_date", "intended_move_out_date",

        ]


class TenantDetailSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    unit_label = serializers.CharField(source="unit.label", read_only=True)
    building_name = serializers.CharField(source="unit.building.name", read_only=True)
    building_id = serializers.IntegerField(source="unit.building.id", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    documents = TenantDocumentSerializer(many=True, read_only=True)
    # Payment analytics
    total_paid = serializers.SerializerMethodField()
    total_arrears = serializers.SerializerMethodField()

    class Meta:
        model = Tenant
        fields = [
            "id", "full_name", "first_name", "last_name", "id_number",
            "phone", "email", "emergency_contact", "emergency_phone",
            "unit", "unit_label", "building_name", "building_id",
            "monthly_rent", "deposit_paid", "due_day",

            "deposit_refund_percentage", "deposit_refund_amount",
            "move_in_date", "move_out_date",
            "notice_date", "intended_move_out_date",
            "status", "status_display", "move_out_notes", "notes",
            "documents", "total_paid", "total_arrears",
            "created_at", "updated_at",
        ]
        read_only_fields = ["status", "move_out_date", "move_out_notes", "created_at", "updated_at"]

    def get_total_paid(self, obj):
        from django.db.models import Sum
        result = obj.payments.aggregate(total=Sum("amount"))["total"]
        return float(result or 0)

    def get_total_arrears(self, obj):
        from django.db.models import Sum
        result = obj.arrears.filter(is_cleared=False).aggregate(total=Sum("balance"))["total"]
        return float(result or 0)


class TenantCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = [
            "id", "first_name", "last_name", "id_number", "phone", "email",
            "emergency_contact", "emergency_phone", "unit",
            "monthly_rent", "deposit_paid", "due_day", "move_in_date", "notes",

        ]

    def validate_unit(self, unit):
        from apps.buildings.models import UnitStatus
        if unit.status not in (UnitStatus.VACANT,):
            raise serializers.ValidationError("This unit is not vacant.")
        if Tenant.objects.filter(unit=unit, status__in=["active", "notice_given"]).exists():
            raise serializers.ValidationError("This unit already has an active tenant.")
        return unit


class TenantEditSerializer(serializers.ModelSerializer):
    """For admin editing of tenant details — rent, deposit, status."""

    class Meta:
        model = Tenant
        fields = [
            "first_name", "last_name", "phone", "email",
            "emergency_contact", "emergency_phone",
            "monthly_rent", "deposit_paid", "due_day", "deposit_refund_percentage",
            "notes",

        ]


class MoveOutNoticeSerializer(serializers.Serializer):
    """Record that a tenant has given move-out notice."""
    notice_date = serializers.DateField()
    intended_move_out_date = serializers.DateField()
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class MoveOutSerializer(serializers.Serializer):
    """Finalise move-out."""
    move_out_date = serializers.DateField(required=False)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    deposit_refund_percentage = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, default=100)


class DocumentUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    doc_type = serializers.ChoiceField(choices=DocumentType.choices, default=DocumentType.OTHER)
