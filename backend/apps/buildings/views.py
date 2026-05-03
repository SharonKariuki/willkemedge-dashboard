"""Building, Unit and MaintenanceRequest API views."""
from django.db import transaction
from django.db.models import Count, Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.expenses.models import Expense, ExpenseCategory

from .models import Building, MaintenanceRequest, Unit, UnitStatus
from .serializers import (
    BuildingDetailSerializer,
    BuildingSerializer,
    MaintenanceRequestSerializer,
    UnitSerializer,
    UnitStatusSummarySerializer,
)


class BuildingViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Building.objects.annotate(
            unit_count=Count("units"),
            occupied_count=Count("units", filter=~Q(units__status=UnitStatus.VACANT)),
        ).order_by("name")

    def get_serializer_class(self):
        if self.action in ("retrieve", "bulk_create_units"):
            return BuildingDetailSerializer
        return BuildingSerializer

    @action(detail=True, methods=["post"], url_path="bulk-create-units")
    def bulk_create_units(self, request, pk=None):
        building = self.get_object()
        units_data = request.data.get("units", [])
        if not units_data:
            return Response({"detail": "No units provided."}, status=status.HTTP_400_BAD_REQUEST)

        serializers_list = [UnitSerializer(data={**u, "building": building.pk}) for u in units_data]
        errors = []
        for i, s in enumerate(serializers_list):
            if not s.is_valid():
                errors.append({"index": i, "errors": s.errors})
        if errors:
            return Response({"detail": "Validation failed.", "errors": errors}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            for s in serializers_list:
                s.save()

        refreshed = self.get_queryset().get(pk=building.pk)
        return Response(BuildingDetailSerializer(refreshed, context={"request": request}).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="adjust-rent")
    def adjust_rent(self, request, pk=None):
        """
        POST /api/buildings/{id}/adjust-rent/
        Input: {"amount": 1000, "type": "fixed"|"percent"}
        """
        building = self.get_object()
        adj_amount = request.data.get("amount")
        adj_type = request.data.get("type", "fixed")

        if not adj_amount:
            return Response({"detail": "Amount is required."}, status=400)

        with transaction.atomic():
            units = building.units.all()
            for unit in units:
                old_rent = float(unit.monthly_rent)
                if adj_type == "percent":
                    new_rent = old_rent * (1 + float(adj_amount) / 100)
                else:
                    new_rent = old_rent + float(adj_amount)
                unit.monthly_rent = round(new_rent, 0)
                unit.save(update_fields=["monthly_rent", "updated_at"])

        return Response({"detail": f"Rent adjusted for {units.count()} units in {building.name}."})

    @action(detail=True, methods=["get"], url_path="maintenance-summary")
    def maintenance_summary(self, request, pk=None):
        """GET /api/buildings/{id}/maintenance-summary/"""
        building = self.get_object()
        requests = MaintenanceRequest.objects.filter(unit__building=building)
        
        total_cost = requests.aggregate(total=Sum("cost"))["total"] or 0
        status_counts = requests.values("status").annotate(count=Count("id"))
        
        return Response({
            "building_name": building.name,
            "total_requests": requests.count(),
            "total_cost": float(total_cost),
            "breakdown": {s["status"]: s["count"] for s in status_counts}
        })



class UnitViewSet(viewsets.ModelViewSet):
    serializer_class = UnitSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Unit.objects.select_related("building").order_by("building__name", "floor", "label")
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
        qs = Unit.objects.all()
        building_id = request.query_params.get("building")
        if building_id:
            qs = qs.filter(building_id=building_id)
        total = qs.count()
        counts = {v: qs.filter(status=v).count() for v, _ in UnitStatus.choices}
        data = {
            "total": total,
            "vacant": counts.get(UnitStatus.VACANT, 0),
            "occupied_paid": counts.get(UnitStatus.OCCUPIED_PAID, 0),
            "occupied_partial": counts.get(UnitStatus.OCCUPIED_PARTIAL, 0),
            "occupied_unpaid": counts.get(UnitStatus.OCCUPIED_UNPAID, 0),
            "arrears": counts.get(UnitStatus.ARREARS, 0),
            "under_maintenance": counts.get(UnitStatus.UNDER_MAINTENANCE, 0),
        }
        return Response(UnitStatusSummarySerializer(data).data)

    @action(detail=True, methods=["patch"], url_path="set-status")
    def set_status(self, request, pk=None):
        """PATCH /api/units/{id}/set-status/ — manually set status (e.g. under_maintenance)."""
        unit = self.get_object()
        new_status = request.data.get("status")
        if new_status not in dict(UnitStatus.choices):
            return Response({"detail": "Invalid status."}, status=status.HTTP_400_BAD_REQUEST)
        unit.status = new_status
        unit.save(update_fields=["status", "updated_at"])
        return Response(UnitSerializer(unit).data)


class MaintenanceRequestViewSet(viewsets.ModelViewSet):
    """CRUD for maintenance requests. Auto-creates an Expense when cost > 0."""
    serializer_class = MaintenanceRequestSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = MaintenanceRequest.objects.select_related("unit", "unit__building")
        unit_id = self.request.query_params.get("unit")
        if unit_id:
            qs = qs.filter(unit_id=unit_id)
        building_id = self.request.query_params.get("building")
        if building_id:
            qs = qs.filter(unit__building_id=building_id)
        req_status = self.request.query_params.get("status")
        if req_status:
            qs = qs.filter(status=req_status)
        return qs.order_by("-reported_date")

    def perform_create(self, serializer):
        with transaction.atomic():
            instance = serializer.save()
            # Auto-sync cost to Expenses tab if cost > 0
            if instance.cost and instance.cost > 0:
                cat, _ = ExpenseCategory.objects.get_or_create(
                    name="Maintenance & Repairs",
                    defaults={"description": "Auto-created from maintenance requests"},
                )
                expense = Expense.objects.create(
                    date=instance.reported_date,
                    building=instance.unit.building,
                    category=cat,
                    amount=instance.cost,
                    description=f"Maintenance: {instance.description[:200]}",
                    reference=f"MNT-{instance.pk}",
                    period_month=instance.reported_date.month,
                    period_year=instance.reported_date.year,
                    notes=f"Auto-created from maintenance request #{instance.pk}",
                )
                instance.expense = expense
                instance.save(update_fields=["expense"])
            # Set unit status to under_maintenance
            unit = instance.unit
            if unit.status == UnitStatus.VACANT:
                unit.status = UnitStatus.UNDER_MAINTENANCE
                unit.save(update_fields=["status"])

    def perform_update(self, serializer):
        with transaction.atomic():
            instance = serializer.save()
            # If marked done, revert unit to vacant if no active tenant
            if instance.status == "done":
                from apps.tenants.models import TenantStatus
                has_active = instance.unit.tenants.filter(status=TenantStatus.ACTIVE).exists()
                if not has_active and instance.unit.status == UnitStatus.UNDER_MAINTENANCE:
                    instance.unit.status = UnitStatus.VACANT
                    instance.unit.save(update_fields=["status"])
            # Sync cost to linked expense if it changed
            if instance.expense and instance.cost != instance.expense.amount:
                instance.expense.amount = instance.cost
                instance.expense.save(update_fields=["amount"])
