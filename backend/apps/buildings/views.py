"""Building and Unit API views."""
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
        if self.action == "retrieve":
            return BuildingDetailSerializer
        return BuildingSerializer


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
