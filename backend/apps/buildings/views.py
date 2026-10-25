"""Building, Unit and MaintenanceRequest API views."""
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Count, Prefetch, Q, Sum
from django.http import HttpResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts import audit
from apps.accounts.permissions import CanRecordMoney

from . import photos, spaces
from .maintenance import sync_maintenance_expense
from .models import (
    OCCUPIED_UNIT_STATUSES,
    Building,
    MaintenanceRequest,
    Unit,
    UnitStatus,
)
from .serializers import (
    BuildingDetailSerializer,
    BuildingSerializer,
    MaintenanceRequestSerializer,
    ReconfigureSpaceSerializer,
    UnitSerializer,
    UnitStatusSummarySerializer,
)


class BuildingViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Building.objects.annotate(
            unit_count=Count("units"),
            occupied_count=Count(
                "units", filter=Q(units__status__in=OCCUPIED_UNIT_STATUSES)
            ),
        ).defer("photo").order_by("name")
        if self.action == "retrieve":
            # The detail payload serialises every unit with its combined space.
            qs = qs.prefetch_related(Prefetch(
                "units",
                queryset=Unit.objects.select_related("combined_into")
                .prefetch_related("combined_units", "combined_into__combined_units"),
            ))
        return qs

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

    @action(
        detail=True, methods=["get", "put", "delete"], url_path="photo",
        parser_classes=[MultiPartParser, FormParser],
    )
    def photo(self, request, pk=None):
        """GET/PUT/DELETE /api/buildings/{id}/photo/ — the building's cover photo.

        PUT takes a multipart ``photo`` file. GET returns the image bytes, or 404
        when there is none and the card should show its placeholder.
        """
        building = self.get_object()
        if request.method == "GET":
            data = Building.objects.filter(pk=building.pk).values_list("photo", flat=True).first()
            if not data or not building.photo_content_type:
                return Response(status=status.HTTP_404_NOT_FOUND)
            response = HttpResponse(bytes(data), content_type=building.photo_content_type)
            response["Cache-Control"] = "private, max-age=86400"
            response["X-Content-Type-Options"] = "nosniff"
            return response
        if request.method == "DELETE":
            photos.clear_photo(building)
            return Response(status=status.HTTP_204_NO_CONTENT)
        upload = request.FILES.get("photo")
        if upload is None:
            return Response({"detail": "Attach a photo."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            photos.set_photo(building, upload)
        except DjangoValidationError as exc:
            return Response({"detail": " ".join(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(BuildingSerializer(self.get_queryset().get(pk=building.pk)).data)

    @action(detail=True, methods=["post"], url_path="adjust-rent")
    def adjust_rent(self, request, pk=None):
        """
        POST /api/buildings/{id}/adjust-rent/
        Input: {"amount": 1000, "type": "fixed"|"percent"}

        Changes each unit's LISTED rent, the figure a new letting starts from.
        It does not change what current tenants are billed: that is their own
        Tenant.monthly_rent, agreed per tenancy and changed on the tenant's
        page. The response says how many current tenancies were left as is.
        """
        from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

        from apps.tenants.models import CURRENT_STATUSES, Tenant

        building = self.get_object()
        adj_type = request.data.get("type", "fixed")
        if adj_type not in ("fixed", "percent"):
            return Response({"detail": "Type must be fixed or percent."}, status=400)
        try:
            adj_amount = Decimal(str(request.data.get("amount", "")).strip())
        except InvalidOperation:
            return Response({"detail": "Amount must be a number."}, status=400)
        if not adj_amount.is_finite() or adj_amount == 0:
            return Response({"detail": "Amount is required."}, status=400)
        if adj_type == "percent" and not (Decimal("-100") < adj_amount <= Decimal("100")):
            return Response({"detail": "A percentage change must be above -100% and at most 100%."}, status=400)

        units = list(building.units.all())
        new_rents = {}
        for unit in units:
            old_rent = unit.monthly_rent
            if adj_type == "percent":
                new_rent = old_rent * (1 + adj_amount / 100)
            else:
                new_rent = old_rent + adj_amount
            new_rent = new_rent.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            if new_rent < 0:
                return Response(
                    {"detail": f"That would make {unit.label}'s rent negative (KES {new_rent:,})."},
                    status=400,
                )
            new_rents[unit.pk] = (old_rent, new_rent)

        with transaction.atomic():
            for unit in units:
                unit.monthly_rent = new_rents[unit.pk][1]
                unit.save(update_fields=["monthly_rent", "updated_at"])
            audit.record(
                action="building.adjust_rent",
                object_type="building",
                object_id=building.pk,
                object_label=building.name,
                summary=f"Adjusted listed rent of {len(units)} units in {building.name} "
                        f"by {adj_amount}{'%' if adj_type == 'percent' else ' KES'}",
                old_values={str(pk): str(v[0]) for pk, v in new_rents.items()},
                new_values={str(pk): str(v[1]) for pk, v in new_rents.items()},
                actor=request.user,
                is_financial=True,
            )

        current = Tenant.objects.filter(unit__building=building, status__in=CURRENT_STATUSES).count()
        return Response({
            "detail": f"Listed rent adjusted for {len(units)} units in {building.name}. "
                      f"{current} current tenanc{'y' if current == 1 else 'ies'} keep their agreed rent; "
                      "change those on each tenant's page.",
            "units": len(units),
            "current_tenancies_unchanged": current,
        })

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
        from apps.tenants.models import Tenant, TenantStatus

        active_tenants = Tenant.objects.filter(
            status__in=[TenantStatus.ACTIVE, TenantStatus.NOTICE_GIVEN]
        ).order_by("-move_in_date")

        qs = (
            Unit.objects.select_related("building", "combined_into")
            .prefetch_related(
                Prefetch("tenants", queryset=active_tenants, to_attr="active_tenants"),
                Prefetch("combined_into__tenants", queryset=active_tenants, to_attr="active_tenants"),
                "combined_units",
                "combined_into__combined_units",
            )
            .order_by("building__name", "floor", "label")
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

    @action(
        detail=True, methods=["post"], url_path="reconfigure-space",
        permission_classes=[CanRecordMoney],
    )
    def reconfigure_space(self, request, pk=None):
        """POST /api/units/{head}/reconfigure-space/ — combine commercial units.

        Body: ``add`` / ``remove`` (unit ids) and optionally ``monthly_rent``,
        the agreed base rent for the space afterwards. Record-money roles only:
        the change moves what the tenant is billed.
        """
        head = self.get_object()
        ser = ReconfigureSpaceSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            spaces.reconfigure_space(
                head,
                add=ser.validated_data["add"],
                remove=ser.validated_data["remove"],
                monthly_rent=ser.validated_data.get("monthly_rent"),
                actor=request.user,
            )
        except DjangoValidationError as exc:
            return Response({"detail": " ".join(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(UnitSerializer(self.get_queryset().get(pk=head.pk)).data)

    @action(detail=True, methods=["patch"], url_path="set-status")
    def set_status(self, request, pk=None):
        """PATCH /api/units/{id}/set-status/ — manually set status (e.g. under_maintenance)."""
        from apps.tenants.models import CURRENT_STATUSES

        unit = self.get_object()
        new_status = request.data.get("status")
        if new_status not in dict(UnitStatus.choices):
            return Response({"detail": "Invalid status."}, status=status.HTTP_400_BAD_REQUEST)
        # The status has to agree with the tenancy. Marking a let unit vacant
        # hid the tenant from occupancy and let a second tenant be moved in on
        # top of them; marking an empty unit occupied invents a tenant.
        if unit.combined_into_id:
            return Response(
                {"detail": f"{unit.label} is part of the space {unit.space_label}; "
                           f"set the status on {unit.combined_into.label}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        occupant = unit.tenants.filter(status__in=CURRENT_STATUSES).first()
        if occupant and new_status in (UnitStatus.VACANT, UnitStatus.UNDER_MAINTENANCE):
            return Response(
                {"detail": f"{unit.label} is let to {occupant.full_name}. Move them out first."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not occupant and new_status in OCCUPIED_UNIT_STATUSES:
            return Response(
                {"detail": f"{unit.label} has no current tenant, so it can't be marked occupied. "
                           "Move a tenant in instead."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        old_status = unit.status
        unit.status = new_status
        unit.save(update_fields=["status", "updated_at"])
        if old_status != new_status:
            # Status is otherwise derived from payments and not auto-audited;
            # setting it by hand (e.g. under maintenance) is a decision.
            labels = dict(UnitStatus.choices)
            audit.record(
                action="unit.set_status",
                object_type="unit",
                object_id=unit.pk,
                object_label=unit.label,
                summary=f"Set unit {unit.label} to {labels[new_status]} (was {labels.get(old_status, old_status)})",
                old_values={"status": old_status},
                new_values={"status": new_status},
                actor=request.user,
                is_financial=False,
            )
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
            sync_maintenance_expense(instance)
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
                from apps.tenants.models import CURRENT_STATUSES
                has_active = instance.unit.tenants.filter(status__in=CURRENT_STATUSES).exists()
                if not has_active and instance.unit.status == UnitStatus.UNDER_MAINTENANCE:
                    instance.unit.status = UnitStatus.VACANT
                    instance.unit.save(update_fields=["status"])
            sync_maintenance_expense(instance)
