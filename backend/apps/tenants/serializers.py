"""Tenant serializers."""
from rest_framework import serializers

from .models import DocumentType, Tenant, TenantDocument


class TenantDocumentSerializer(serializers.ModelSerializer):
    doc_type_display = serializers.CharField(source="get_doc_type_display", read_only=True)

    class Meta:
        model = TenantDocument
        fields = [
            "id",
            "tenant",
            "doc_type",
            "doc_type_display",
            "file",
            "original_name",
            "uploaded_at",
        ]
        read_only_fields = ["tenant", "original_name", "uploaded_at"]


class TenantListSerializer(serializers.ModelSerializer):
    """Compact serializer for the tenant list."""

    full_name = serializers.CharField(read_only=True)
    unit_label = serializers.CharField(source="unit.label", read_only=True)
    building_name = serializers.CharField(source="unit.building.name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Tenant
        fields = [
            "id",
            "full_name",
            "first_name",
            "last_name",
            "phone",
            "unit",
            "unit_label",
            "building_name",
            "monthly_rent",
            "status",
            "status_display",
            "move_in_date",
            "move_out_date",
        ]


class TenantDetailSerializer(serializers.ModelSerializer):
    """Full serializer with documents for the detail page."""

    full_name = serializers.CharField(read_only=True)
    unit_label = serializers.CharField(source="unit.label", read_only=True)
    building_name = serializers.CharField(source="unit.building.name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    documents = TenantDocumentSerializer(many=True, read_only=True)

    class Meta:
        model = Tenant
        fields = [
            "id",
            "full_name",
            "first_name",
            "last_name",
            "id_number",
            "phone",
            "email",
            "emergency_contact",
            "emergency_phone",
            "unit",
            "unit_label",
            "building_name",
            "monthly_rent",
            "deposit_paid",
            "move_in_date",
            "move_out_date",
            "status",
            "status_display",
            "move_out_notes",
            "notes",
            "documents",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["status", "move_out_date", "move_out_notes", "created_at", "updated_at"]


class TenantCreateSerializer(serializers.ModelSerializer):
    """Create a new tenant and trigger move-in."""

    class Meta:
        model = Tenant
        fields = [
            "id",
            "first_name",
            "last_name",
            "id_number",
            "phone",
            "email",
            "emergency_contact",
            "emergency_phone",
            "unit",
            "monthly_rent",
            "deposit_paid",
            "move_in_date",
            "notes",
        ]

    def validate_unit(self, unit):
        from apps.buildings.models import UnitStatus

        if unit.status != UnitStatus.VACANT:
            raise serializers.ValidationError("This unit is not vacant.")
        # Check no active tenant on the same unit.
        if Tenant.objects.filter(unit=unit, status="active").exists():
            raise serializers.ValidationError("This unit already has an active tenant.")
        return unit


class MoveOutSerializer(serializers.Serializer):
    """Move-out request body."""

    move_out_date = serializers.DateField(required=False)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class DocumentUploadSerializer(serializers.Serializer):
    """Upload a document for a tenant."""

    file = serializers.FileField()
    doc_type = serializers.ChoiceField(choices=DocumentType.choices, default=DocumentType.OTHER)
