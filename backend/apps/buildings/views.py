"""Building and Unit API views."""
from django.db import transaction
from django.db.models import Count, Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Building, Unit, UnitStatus
from .serializers import (
    BuildingDetailSerializer,
    BuildingSerializer,
    UnitSerializer,
    UnitStatusSummarySerializer,
)


class BuildingViewSet(viewsets.ModelViewSet):
    """
    CRUD for buildings.
    List annotates unit_count and occupied_count for the index page.
    Retrieve returns the full building + nested units.
    POST /buildings/{id}/bulk-create-units/ creates multiple units atomically.
    """

    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Building.objects.annotate(
            unit_count=Count("units"),
            occupied_count=Count(
                "units",
                filter=~Q(units__status=UnitStatus.VACANT),
            ),
        ).order_by("name")

    def get_serializer_class(self):
        if self.action in ("retrieve", "bulk_create_units"):
            return BuildingDetailSerializer
        return BuildingSerializer

    @action(detail=True, methods=["post"], url_path="bulk-create-units")
    def bulk_create_units(self, request, pk=None):
        """
        POST /api/buildings/{id}/bulk-create-units/

        Body: { "units": [ { label, floor, unit_type, monthly_rent, notes? }, ... ] }

        Creates all units atomically. Returns the updated BuildingDetail.
        """
        building = self.get_object()
        units_data = request.data.get("units", [])

        if not units_data:
            return Response(
                {"detail": "No units provided."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializers_list = [
            UnitSerializer(data={**u, "building": building.pk}) for u in units_data
        ]

        # Validate all before saving any.
        errors = []
        for i, s in enumerate(serializers_list):
            if not s.is_valid():
                errors.append({"index": i, "errors": s.errors})
        if errors:
            return Response(
                {"detail": "Validation failed.", "errors": errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            for s in serializers_list:
                s.save()

        # Re-fetch with annotations so counts are correct.
        refreshed = self.get_queryset().get(pk=building.pk)
        out = BuildingDetailSerializer(refreshed, context={"request": request})
        return Response(out.data, status=status.HTTP_201_CREATED)


class UnitViewSet(viewsets.ModelViewSet):
    """
    CRUD for units.
    Supports filtering by building, status, and unit_type via query params.
    """

    serializer_class = UnitSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Unit.objects.select_related("building").order_by(
            "building__name", "label"
        )

        building_id = self.request.query_params.get("building")
        if building_id:
            qs = qs.filter(building_id=building_id)

        unit_status = self.request.query_params.get("status")
        if unit_status:
            qs = qs.filter(status=unit_status)

        unit_type = self.request.query_params.get("unit_type")
        if unit_type:
            qs = qs.filter(unit_type=unit_type)

        return qs

    @action(detail=False, methods=["get"], url_path="status-summary")
    def status_summary(self, request):
        """
        GET /api/units/status-summary/

        Returns a KPI rollup of unit counts by status.
        """
        qs = Unit.objects.all()

        building_id = request.query_params.get("building")
        if building_id:
            qs = qs.filter(building_id=building_id)

        total = qs.count()
        counts = {}
        for choice_val, _ in UnitStatus.choices:
            counts[choice_val] = qs.filter(status=choice_val).count()

        data = {
            "total": total,
            "vacant": counts[UnitStatus.VACANT],
            "occupied_paid": counts[UnitStatus.OCCUPIED_PAID],
            "occupied_partial": counts[UnitStatus.OCCUPIED_PARTIAL],
            "occupied_unpaid": counts[UnitStatus.OCCUPIED_UNPAID],
            "arrears": counts[UnitStatus.ARREARS],
        }
        serializer = UnitStatusSummarySerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)
