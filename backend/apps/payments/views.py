"""Payment API views."""
import random
import string

from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.tenants.models import Tenant

from .models import Arrears, Payment, PaymentSource
from .serializers import (
    ArrearsSerializer,
    CollectionProgressSerializer,
    PaymentCreateSerializer,
    PaymentSerializer,
)
from .services import get_collection_progress, process_payment


class MockPaymentSerializer(serializers.Serializer):
    tenant = serializers.IntegerField(min_value=1)
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=1)
    source = serializers.ChoiceField(
        choices=[PaymentSource.MPESA, PaymentSource.BANK, PaymentSource.CASH]
    )


def _mock_reference(source: str) -> str:
    prefix = {"mpesa": "MP", "bank": "BK", "cash": "CH"}.get(source, "RX")
    tail = "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
    return f"{prefix}{tail}"


def _mock_notes(source: str) -> str:
    return {
        "mpesa": "Simulated M-Pesa C2B payment",
        "bank": "Simulated bank transfer",
        "cash": "Cash paid at the office",
    }.get(source, "Mock payment")


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

    @action(detail=False, methods=["post"], url_path="mock")
    def mock(self, request):
        """
        POST /api/payments/mock/
        body: {tenant, amount, source}

        Simulates a realistic payment from M-Pesa, bank, or cash with an
        auto-generated reference. Runs the same processing pipeline as the
        real webhooks so arrears + unit status update correctly.
        """
        serializer = MockPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            tenant = Tenant.objects.get(pk=data["tenant"])
        except Tenant.DoesNotExist:
            return Response(
                {"detail": "Tenant not found."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        now = timezone.now()
        source = data["source"]
        payment = process_payment(
            tenant=tenant,
            amount=data["amount"],
            payment_date=now.date(),
            period_month=now.month,
            period_year=now.year,
            source=source,
            reference=_mock_reference(source),
            notes=_mock_notes(source),
        )
        return Response(
            PaymentSerializer(payment).data,
            status=status.HTTP_201_CREATED,
        )

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
