"""Payment API views."""
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Arrears, Payment
from .serializers import (
    ArrearsSerializer,
    CollectionProgressSerializer,
    PaymentCreateSerializer,
    PaymentSerializer,
)
from .services import get_collection_progress, process_payment


class PaymentViewSet(viewsets.ModelViewSet):
    """
    CRUD for payments.
    Create triggers payment processing (arrears update + unit status recalc).
    """

    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        qs = Payment.objects.select_related(
            "tenant", "tenant__unit", "tenant__unit__building"
        )

        tenant_id = self.request.query_params.get("tenant")
        if tenant_id:
            qs = qs.filter(tenant_id=tenant_id)

        source = self.request.query_params.get("source")
        if source:
            qs = qs.filter(source=source)

        period_month = self.request.query_params.get("period_month")
        period_year = self.request.query_params.get("period_year")
        if period_month and period_year:
            qs = qs.filter(period_month=period_month, period_year=period_year)

        return qs

    def get_serializer_class(self):
        if self.action == "create":
            return PaymentCreateSerializer
        return PaymentSerializer

    def perform_create(self, serializer):
        data = serializer.validated_data
        process_payment(
            tenant=data["tenant"],
            amount=data["amount"],
            payment_date=data["payment_date"],
            period_month=data["period_month"],
            period_year=data["period_year"],
            source=data.get("source", "cash"),
            reference=data.get("reference", ""),
            notes=data.get("notes", ""),
        )

    @action(detail=False, methods=["get"], url_path="recent")
    def recent(self, request):
        """GET /api/payments/recent/ — last 10 payments."""
        qs = self.get_queryset()[:10]
        return Response(PaymentSerializer(qs, many=True).data)

    @action(detail=False, methods=["get"], url_path="collection-progress")
    def collection_progress(self, request):
        """GET /api/payments/collection-progress/?month=4&year=2026"""
        now = timezone.now()
        month = int(request.query_params.get("month", now.month))
        year = int(request.query_params.get("year", now.year))
        data = get_collection_progress(month, year)
        serializer = CollectionProgressSerializer(data)
        return Response(serializer.data)


class ArrearsViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only arrears list."""

    serializer_class = ArrearsSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Arrears.objects.select_related("tenant", "tenant__unit")

        cleared = self.request.query_params.get("cleared")
        if cleared == "false":
            qs = qs.filter(is_cleared=False)
        elif cleared == "true":
            qs = qs.filter(is_cleared=True)

        tenant_id = self.request.query_params.get("tenant")
        if tenant_id:
            qs = qs.filter(tenant_id=tenant_id)

        return qs
