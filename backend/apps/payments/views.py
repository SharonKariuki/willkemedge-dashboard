"""Payment API views."""
import random
import string

from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.tenants.models import Tenant

from .models import Arrears, Payment, PaymentSource, Transaction
from .pdf_service import render_to_pdf
from .receipt_service import generate_receipt
from .serializers import (
    ArrearsSerializer,
    CollectionProgressSerializer,
    PaymentCreateSerializer,
    PaymentSerializer,
    ReceiptSerializer,
    TransactionSerializer,
)
from .services import get_collection_progress, process_payment
from .tasks import generate_monthly_arrears, send_payment_confirmation


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
        payment = process_payment(
            tenant=data["tenant"],
            amount=data["amount"],
            payment_date=data["payment_date"],
            period_month=data["period_month"],
            period_year=data["period_year"],
            source=data.get("source", "cash"),
            reference=data.get("reference", ""),
            notes=data.get("notes", ""),
        )
        send_payment_confirmation.delay(payment.id)

    @action(detail=False, methods=["get"], url_path="recent")
    def recent(self, request):
        """GET /api/payments/recent/ — last 10 payments."""
        qs = self.get_queryset()[:10]
        return Response(PaymentSerializer(qs, many=True).data)

    @action(detail=True, methods=["post"], url_path="resend-receipt")
    def resend_receipt(self, request, pk=None):
        """POST /api/payments/{id}/resend-receipt/ — re-fire the SMS+email receipt."""
        payment = self.get_object()
        send_payment_confirmation.delay(payment.id)
        return Response({"detail": "Receipt queued for resend."})

    @action(detail=False, methods=["post"], url_path="mock")
    def mock(self, request):
        """
        POST /api/payments/mock/
        Simulates a realistic payment. Runs the full processing pipeline
        so arrears + unit status + Transaction are all created correctly.
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

    @action(detail=False, methods=["post"], url_path="sync")
    def sync(self, request):
        """POST /api/payments/arrears/sync/ — trigger monthly arrears generation."""
        generate_monthly_arrears()
        return Response({"detail": "Arrears synchronized for active tenants."})

    @action(detail=True, methods=["post"], url_path="waive")
    def waive(self, request, pk=None):
        """POST /api/payments/arrears/{id}/waive/"""
        arrears = self.get_object()
        if arrears.is_cleared:
            return Response({"detail": "Already cleared."}, status=400)

        notes = request.data.get("notes", "Waived by admin")
        amount = arrears.balance

        arrears.waived_amount = amount
        arrears.balance = 0
        arrears.is_cleared = True
        arrears.waive_notes = notes
        arrears.save()

        # Update unit status if cleared
        from apps.buildings.services import recalculate_unit_status
        recalculate_unit_status(arrears.tenant.unit, float(arrears.amount_paid))

        return Response(ArrearsSerializer(arrears).data)



class TransactionViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only Transaction list and detail.
    GET /api/payments/transactions/
    GET /api/payments/transactions/{id}/
    GET /api/payments/transactions/{id}/receipt/
    """

    serializer_class = TransactionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Transaction.objects.select_related(
            "tenant",
            "tenant__unit",
            "tenant__unit__building",
            "payment",
        )

        tenant_id = self.request.query_params.get("tenant")
        if tenant_id:
            qs = qs.filter(tenant_id=tenant_id)

        classification = self.request.query_params.get("classification")
        if classification:
            qs = qs.filter(unit_classification=classification.upper())

        return qs

    @action(detail=True, methods=["get"], url_path="receipt")
    def receipt(self, request, pk=None):
        """
        GET /api/payments/transactions/{id}/receipt/

        Returns receipt data built from stored Transaction fields only.
        Optionally include outstanding_balance if the tenant has open arrears.
        """
        txn = self.get_object()

        # Fetch outstanding balance from latest arrears if available.
        outstanding = None
        try:
            from .models import Arrears
            latest_arrears = (
                Arrears.objects.filter(tenant=txn.tenant, is_cleared=False)
                .order_by("-period_year", "-period_month")
                .first()
            )
            if latest_arrears:
                outstanding = latest_arrears.balance
        except Exception:
            pass

        receipt_data = generate_receipt(txn, outstanding_balance=outstanding)
        serializer = ReceiptSerializer(receipt_data)
        return Response(serializer.data)

    @action(detail=True, methods=["get"], url_path="receipt-pdf")
    def receipt_pdf(self, request, pk=None):
        """
        GET /api/payments/transactions/{id}/receipt-pdf/

        Returns the official Wilkem rent statement for the transaction's tenant,
        as of the payment date — the document the tenant receives after paying.
        """
        from django.http import HttpResponse

        from .statement_service import build_statement

        txn = self.get_object()
        as_of = txn.payment.payment_date if txn.payment_id else None
        data = build_statement(txn.tenant, statement_date=as_of, as_of=as_of)

        pdf = render_to_pdf("payments/statement_pdf.html", data)
        if pdf:
            safe_name = txn.tenant.full_name.replace(" ", "_")
            filename = f"Rent_Statement_{safe_name}.pdf"
            response = HttpResponse(pdf, content_type="application/pdf")
            response["Content-Disposition"] = f'attachment; filename="{filename}"'
            return response
        return Response({"detail": "PDF generation failed."}, status=500)

