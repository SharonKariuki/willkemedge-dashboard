"""Serializers for Building, Unit, and MaintenanceRequest."""
from rest_framework import serializers

from .models import Building, MaintenanceRequest, Unit


class UnitSerializer(serializers.ModelSerializer):
    building_name = serializers.CharField(source="building.name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    classification_display = serializers.CharField(source="get_classification_display", read_only=True)

    class Meta:
        model = Unit
        fields = [
            "id", "building", "building_name", "label", "floor", "unit_type",
            "classification", "classification_display", "monthly_rent",
            "status", "status_display", "notes", "created_at", "updated_at",
        ]
        read_only_fields = ["status", "created_at", "updated_at"]


class BuildingSerializer(serializers.ModelSerializer):
    unit_count = serializers.IntegerField(read_only=True)
    occupied_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Building
        fields = [
            "id", "name", "address", "total_floors", "notes",
            "unit_count", "occupied_count", "created_at", "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


class BuildingDetailSerializer(BuildingSerializer):
    units = UnitSerializer(many=True, read_only=True)

    class Meta(BuildingSerializer.Meta):
        fields = BuildingSerializer.Meta.fields + ["units"]


class MaintenanceRequestSerializer(serializers.ModelSerializer):
    unit_label = serializers.CharField(source="unit.label", read_only=True)
    building_name = serializers.CharField(source="unit.building.name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = MaintenanceRequest
        fields = [
            "id", "unit", "unit_label", "building_name", "description",
            "cost", "status", "status_display", "reported_date",
            "completed_date", "notes", "created_at", "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


class UnitStatusSummarySerializer(serializers.Serializer):
    total = serializers.IntegerField()
    vacant = serializers.IntegerField()
    occupied_paid = serializers.IntegerField()
    occupied_partial = serializers.IntegerField()
    occupied_unpaid = serializers.IntegerField()
    arrears = serializers.IntegerField()
    under_maintenance = serializers.IntegerField()
