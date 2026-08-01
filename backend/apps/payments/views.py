"""Payment API views."""
import random
import string
from decimal import Decimal

from django.conf import settings
from django.db import transaction as db_transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts import audit
from apps.accounts.permissions import CanForgiveMoney, CanRecordMoney
from apps.tenants.models import Tenant

from .models import (
    Arrears,
    CoopIpnEvent,
    CoopIpnStatus,
    Payment,
    PaymentSource,
    PaymentType,
    Transaction,
    UtilityCharge,
)
from .pdf_service import render_to_pdf
from .receipt_service import generate_receipt
from .serializers import (
    ArrearsSerializer,
    CollectionProgressSerializer,
    MeterReadingSerializer,
    PaymentCreateSerializer,
    PaymentSerializer,
    ReceiptSerializer,
    TransactionSerializer,
    UtilityChargeSerializer,
)
from .services import (
    IdempotencyConflict,
    get_collection_progress,
    process_payment,
    void_payment,
)
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

    permission_classes = [CanRecordMoney]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        qs = Payment.objects.select_related(
            "tenant", "tenant__unit", "tenant__unit__building"
        )

        # Voided payments are excluded by default so lists and totals agree with
        # arrears and the ledger; ?include_void=true surfaces them for audit.
        if self.request.query_params.get("include_void") != "true":
            qs = qs.filter(voided_at__isnull=True)

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

    def create(self, request, *args, **kwargs):
        """Wrap create so a reference collision is a 409, never a silent swallow."""
        try:
            return super().create(request, *args, **kwargs)
        except IdempotencyConflict as exc:
            return Response(
                {
                    "detail": str(exc),
                    "existing_payment_id": exc.existing.pk,
                },
                status=status.HTTP_409_CONFLICT,
            )

    def perform_create(self, serializer):
        data = serializer.validated_data
        reference = data.get("reference", "")
        payment = process_payment(
            tenant=data["tenant"],
            amount=data["amount"],
            payment_date=data["payment_date"],
            period_month=data["period_month"],
            period_year=data["period_year"],
            source=data.get("source", "cash"),
            payment_type=data.get("payment_type", PaymentType.RENT),
            reference=reference,
            notes=data.get("notes", ""),
            # A referenced manual payment is a single event: dedupe double-submits
            # (retry / double-click) on (tenant, reference). Blank reference = no
            # key, so unreferenced cash entries behave exactly as before.
            idempotency_key=reference,
            created_by=self.request.user,
        )
        audit.record(
            actor=self.request.user,
            action="payment.create",
            object_type="payment",
            object_id=payment.pk,
            summary=f"Recorded KES {payment.amount} for {payment.tenant} ({payment.period_month}/{payment.period_year})",
            new_values={
                "amount": payment.amount,
                "payment_type": payment.payment_type,
                "reference": payment.reference,
                "payment_date": payment.payment_date,
            },
        )
        send_payment_confirmation.delay(payment.id)

    @action(detail=True, methods=["post"], url_path="void", permission_classes=[CanForgiveMoney])
    def void(self, request, pk=None):
        """POST /api/payments/{id}/void/ — unwind a payment (owner only).

        Marks the row void and posts a mirror-image reversal to the ledger. The
        original entry and the Payment row are both preserved for audit.
        """
        payment = get_object_or_404(Payment, pk=pk)
        if payment.voided_at:
            return Response(
                {"detail": "Payment is already void."}, status=status.HTTP_409_CONFLICT
            )
        reason = (request.data.get("reason") or "").strip()
        if not reason:
            return Response(
                {"detail": "A reason is required to void a payment."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        void_payment(payment, actor=request.user, reason=reason)
        return Response(PaymentSerializer(payment).data)

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

        DEVELOPMENT ONLY. This creates a real Payment, a real Transaction and a
        real journal entry crediting rental income — money that does not exist.
        It is unreachable unless DEBUG is on.
        """
        if not settings.DEBUG:
            raise Http404

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
        mock_reference = _mock_reference(source)
        payment = process_payment(
            tenant=tenant,
            amount=data["amount"],
            payment_date=now.date(),
            period_month=now.month,
            period_year=now.year,
            source=source,
            reference=mock_reference,
            notes=_mock_notes(source),
            idempotency_key=mock_reference,
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

    @action(
        detail=True, methods=["post"], url_path="waive",
        permission_classes=[CanForgiveMoney],
    )
    def waive(self, request, pk=None):
        """POST /api/payments/arrears/{id}/waive/ — write debt off (owner only).

        Waiving is forgiving money, so it is deliberately a different privilege
        from recording it: an accountant may enter receipts but not write a
        balance off.
        """
        arrears = self.get_object()
        if arrears.is_cleared:
            return Response({"detail": "Already cleared."}, status=400)

        notes = request.data.get("notes", "Waived by admin")
        waived_now = arrears.balance

        with db_transaction.atomic():
            # Fold the outstanding balance into any prior waiver rather than
            # overwriting it, so a partial waiver already on record is not lost.
            arrears.waived_amount = (arrears.waived_amount or Decimal("0")) + arrears.balance
            arrears.balance = Decimal("0")
            arrears.is_cleared = True
            arrears.waive_notes = notes
            arrears.save()

            # Reflect the waiver in unit status only for the current period —
            # waiving an old period must not disturb the live unit. Feed the
            # *covered* figure (cash paid + waived + credit) as a Decimal so a
            # full waiver reads as PAID instead of PARTIAL, and measure it
            # against the full obligation including VAT.
            now = timezone.now()
            if arrears.period_month == now.month and arrears.period_year == now.year:
                from apps.buildings.services import recalculate_unit_status
                recalculate_unit_status(
                    arrears.tenant.unit,
                    arrears.covered,
                    obligation=arrears.expected_total,
                )

        audit.record(
            actor=request.user,
            action="arrears.waive",
            object_type="arrears",
            object_id=arrears.pk,
            summary=(
                f"Waived KES {waived_now} for {arrears.tenant} "
                f"({arrears.period_month}/{arrears.period_year}) — {notes}"
            ),
            old_values={"balance": waived_now, "is_cleared": False},
            new_values={"waived_amount": arrears.waived_amount, "is_cleared": True},
        )
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


# ---------------------------------------------------------------------------
# Manual reconciliation — assign unmatched Co-op credits to a tenant
# ---------------------------------------------------------------------------

class UnmatchedCreditSerializer(serializers.ModelSerializer):
    """An unmatched Co-op credit awaiting manual reconciliation."""

    payer_hint = serializers.SerializerMethodField()

    class Meta:
        model = CoopIpnEvent
        fields = [
            "id", "transaction_id", "payment_ref", "account_number", "amount",
            "channel", "narration", "detail", "status", "received_at", "payer_hint",
        ]

    def get_payer_hint(self, obj) -> dict:
        # Surface the parsed payer phone/name so staff can pick the right tenant.
        from .coop_ipn import _parse_narration

        parsed = _parse_narration(obj.narration or "")
        return {"phone": parsed.get("payer_phone", ""), "name": parsed.get("payer_name", "")}


class AssignCreditSerializer(serializers.Serializer):
    tenant = serializers.IntegerField(min_value=1)


class UnmatchedCreditViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Manual reconciliation queue: Co-op credits that couldn't be auto-matched
    to a tenant. Staff list them and POST .../assign/ to book the payment
    against a chosen tenant (mirrors the admin assign action).
    """

    permission_classes = [CanRecordMoney]
    serializer_class = UnmatchedCreditSerializer

    def get_queryset(self):
        return CoopIpnEvent.objects.filter(
            status=CoopIpnStatus.UNMATCHED
        ).order_by("-received_at")

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        body = AssignCreditSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        tenant = Tenant.objects.filter(pk=body.validated_data["tenant"]).first()
        if not tenant:
            return Response({"detail": "Tenant not found."}, status=status.HTTP_404_NOT_FOUND)

        from .services import CreditAlreadyResolved, assign_unmatched_credit
        from .tasks import send_deposit_receipt

        try:
            event, payments = assign_unmatched_credit(
                event_id=pk, tenant=tenant, actor=request.user
            )
        except CoopIpnEvent.DoesNotExist:
            return Response({"detail": "Event not found."}, status=status.HTTP_404_NOT_FOUND)
        except CreditAlreadyResolved as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)

        # Receipt off the atomic block so a broker outage can't roll back the booking.
        try:
            send_deposit_receipt.delay(
                tenant.id,
                str(event.amount),
                event.transaction_id,
                payments[0].payment_date.isoformat(),
            )
        except Exception:  # noqa: BLE001
            pass

        return Response(
            {
                "detail": f"KES {event.amount} assigned to {tenant.full_name} — payment recorded.",
                "payment_id": event.payment_id,
            },
            status=status.HTTP_200_OK,
        )



class UtilityChargeViewSet(viewsets.ReadOnlyModelViewSet):
    """Water/utility charges, plus the staff meter-reading entry point.

    GET  /api/utility-charges/                  — list (filter ?tenant= &month= &year=)
    GET  /api/utility-charges/previous-reading/?tenant=<id>
    POST /api/utility-charges/reading/          — capture a reading, bill the charge
    """

    serializer_class = UtilityChargeSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = UtilityCharge.objects.select_related(
            "tenant", "tenant__unit", "tenant__unit__building"
        ).order_by("-posting_date", "-id")
        tenant = self.request.query_params.get("tenant")
        if tenant:
            qs = qs.filter(tenant_id=tenant)
        month = self.request.query_params.get("month")
        year = self.request.query_params.get("year")
        if month and year:
            qs = qs.filter(period_month=month, period_year=year)
        return qs

    @action(detail=False, methods=["get"], url_path="previous-reading")
    def previous_reading(self, request):
        """Pre-fill the form's 'previous reading' so the meter history stays continuous."""
        from .meter_service import previous_reading_for

        tenant = get_object_or_404(Tenant, pk=request.query_params.get("tenant"))
        reading = previous_reading_for(tenant, label=request.query_params.get("label", "Water Usage"))
        return Response({
            "tenant": tenant.pk,
            "previous_reading": reading,
            "water_rate_per_unit": tenant.unit.building.water_rate_per_unit,
        })

    @action(detail=False, methods=["post"], url_path="reading")
    def capture_reading(self, request):
        """Capture a meter reading -> consumption x tariff -> billed UtilityCharge."""
        from django.core.exceptions import ValidationError as DjangoValidationError

        from .meter_service import bill_meter_reading

        ser = MeterReadingSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        tenant = get_object_or_404(Tenant, pk=data["tenant"])
        try:
            charge = bill_meter_reading(
                tenant=tenant,
                period_month=data["period_month"],
                period_year=data["period_year"],
                closing_reading=data["closing_reading"],
                opening_reading=data.get("opening_reading"),
                label=data.get("label") or "Water Usage",
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages[0] if exc.messages else str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            UtilityChargeSerializer(charge).data, status=status.HTTP_201_CREATED
        )
