"""
Deposit settlement API — the owner's Settle Deposit screen.

    GET  /api/deposit-settlements/?tenant=<id>            settlements, newest first
    GET  /api/deposit-settlements/preview/?tenant=<id>    deposit held, balance owed, form data
    POST /api/deposit-settlements/                        Settle Deposit
    POST /api/deposit-settlements/<id>/mark-sent/         the refund has left
    POST /api/deposit-settlements/<id>/void/              undo a settlement made in error
    GET  /api/deposit-settlements/<id>/statement/         settlement statement PDF

Owner-only (``CanForgiveMoney``), like credits and refunds: settling a deposit
keeps or pays out money that is owed back to the tenant.
"""
from decimal import Decimal

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.permissions import CanForgiveMoney
from apps.expenses.models import ExpenseCategory
from apps.tenants.models import Tenant

from . import deposit_settlement as service
from .credits import CreditError
from .models import (
    DeductionKind,
    DepositDeduction,
    DepositSettlement,
    PaymentSource,
    RefundBasis,
)


def _name(user) -> str:
    if user is None:
        return ""
    return user.get_full_name() or user.email or user.username


def _error(exc) -> Response:
    return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class DepositDeductionSerializer(serializers.ModelSerializer):
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    expense_category_name = serializers.CharField(source="expense_category.name", read_only=True, default="")

    class Meta:
        model = DepositDeduction
        fields = ["id", "kind", "kind_display", "description", "amount", "expense_category", "expense_category_name"]


class DepositSettlementSerializer(serializers.ModelSerializer):
    deductions = DepositDeductionSerializer(many=True, read_only=True)
    refund_basis_display = serializers.CharField(source="get_refund_basis_display", read_only=True)
    refund_status_display = serializers.CharField(source="get_refund_status_display", read_only=True)
    method_display = serializers.CharField(source="get_method_display", read_only=True)
    credit_number = serializers.CharField(source="credit.number", read_only=True, default="")
    created_by_name = serializers.SerializerMethodField()
    is_void = serializers.BooleanField(read_only=True)

    class Meta:
        model = DepositSettlement
        fields = [
            "id", "number", "tenant", "settlement_date", "deposit_held", "balance_owed",
            "deductions", "deductions_total", "refund_basis", "refund_basis_display",
            "refund_percentage", "refund_amount", "refund_status", "refund_status_display",
            "method", "method_display", "paid_to", "reference", "sent_on", "notes",
            "credit", "credit_number", "created_by_name", "created_at",
            "is_void", "voided_at", "void_reason",
        ]

    def get_created_by_name(self, obj):
        return _name(obj.created_by)


class DeductionInputSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=DeductionKind.choices)
    description = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0.01"))
    expense_category = serializers.PrimaryKeyRelatedField(
        queryset=ExpenseCategory.objects.filter(account__isnull=False), required=False, allow_null=True,
    )


class SettleSerializer(serializers.Serializer):
    tenant = serializers.PrimaryKeyRelatedField(queryset=Tenant.objects.all())
    settlement_date = serializers.DateField()
    deductions = DeductionInputSerializer(many=True, required=False, default=list)
    refund_basis = serializers.ChoiceField(choices=RefundBasis.choices)
    refund_amount = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal("0"), required=False, allow_null=True,
    )
    refund_percentage = serializers.DecimalField(
        max_digits=5, decimal_places=2, min_value=Decimal("0"), max_value=Decimal("100"),
        required=False, allow_null=True,
    )
    method = serializers.ChoiceField(choices=PaymentSource.choices, required=False, allow_blank=True, default="")
    paid_to = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    reference = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    already_sent = serializers.BooleanField(default=False)
    sent_on = serializers.DateField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class MarkSentSerializer(serializers.Serializer):
    sent_on = serializers.DateField()
    method = serializers.ChoiceField(choices=PaymentSource.choices)
    reference = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    paid_to = serializers.CharField(max_length=100, required=False, allow_blank=True, allow_null=True, default=None)


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255)


def _amount(value: Decimal) -> str:
    return f"{value:,.2f}"


def day_first(value) -> str:
    return value.strftime("%d/%m/%Y")


def statement_context(s: DepositSettlement) -> dict:
    """What the settlement statement prints, worked out once and formatted."""
    from .statement_generator import DEFAULTS

    tenant = s.tenant
    unit = tenant.unit
    applied = sum(
        (d.amount for d in s.deductions.all() if d.kind == DeductionKind.UNPAID_BALANCE), Decimal("0")
    )
    remaining = max(s.balance_owed - applied, Decimal("0"))
    tenancy = day_first(tenant.move_in_date) + " – " + (
        day_first(tenant.move_out_date) if tenant.move_out_date else "present"
    )
    share = ""
    if s.refund_amount and s.deposit_held:
        pct = (s.refund_amount / s.deposit_held * 100).quantize(Decimal("0.01"))
        share = f"{pct.normalize():f}" if pct != 100 else ""
    return {
        **{k: DEFAULTS[k] for k in ("entity_name", "postal_address", "contact_phone", "contact_email")},
        "s": s,
        "tenant_name": tenant.full_name,
        "premises": f"Unit {unit.label}, {unit.building.name}" if unit else "",
        "tenancy": tenancy,
        "settlement_date": day_first(s.settlement_date),
        "sent_on": day_first(s.sent_on) if s.sent_on else "",
        "issued_on": day_first(timezone.localdate()),
        "method": s.get_method_display() if s.method else "",
        "deposit_held": _amount(s.deposit_held),
        "deductions": [
            {"description": d.description, "kind": d.get_kind_display(), "amount": _amount(d.amount)}
            for d in s.deductions.all()
        ],
        "deductions_total": _amount(s.deductions_total),
        "refund_amount": _amount(s.refund_amount),
        "refund_share": share,
        "balance_owed": _amount(s.balance_owed),
        "applied_to_balance": _amount(applied),
        "remaining_owed": _amount(remaining) if remaining > 0 else "",
    }


class DepositSettlementViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [CanForgiveMoney]
    serializer_class = DepositSettlementSerializer

    def get_queryset(self):
        qs = DepositSettlement.objects.select_related(
            "tenant__unit__building", "credit", "created_by",
        ).prefetch_related("deductions__expense_category")
        tenant_id = self.request.query_params.get("tenant")
        if tenant_id:
            qs = qs.filter(tenant_id=tenant_id)
        return qs

    @action(detail=False, methods=["get"])
    def preview(self, request):
        tenant = get_object_or_404(
            Tenant.objects.select_related("unit"), pk=request.query_params.get("tenant")
        )
        data = service.preview(tenant)
        live = data["settlement"]
        return Response({
            "deposit_held": str(data["deposit_held"]),
            "balance_owed": str(data["balance_owed"]),
            "can_settle": data["can_settle"],
            "tenant_status": tenant.status,
            "tenant_phone": tenant.phone,
            "settlement": DepositSettlementSerializer(live).data if live else None,
            "default_categories": data["default_categories"],
            "expense_categories": [
                {"id": c.pk, "name": c.name}
                for c in ExpenseCategory.objects.filter(account__isnull=False).order_by("name")
            ],
        })

    def create(self, request):
        ser = SettleSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        try:
            settlement = service.settle_deposit(
                tenant=data["tenant"],
                settlement_date=data["settlement_date"],
                deductions=data["deductions"],
                refund_basis=data["refund_basis"],
                refund_amount=data.get("refund_amount"),
                refund_percentage=data.get("refund_percentage"),
                method=data.get("method", ""),
                paid_to=data.get("paid_to", ""),
                reference=data.get("reference", ""),
                sent_on=data.get("sent_on") if data["already_sent"] else None,
                notes=data.get("notes", ""),
                actor=request.user,
            )
        except CreditError as exc:
            return _error(exc)
        return Response(
            DepositSettlementSerializer(self.get_queryset().get(pk=settlement.pk)).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="mark-sent")
    def mark_sent(self, request, pk=None):
        settlement = self.get_object()
        ser = MarkSentSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        try:
            service.mark_refund_sent(
                settlement, sent_on=data["sent_on"], method=data["method"],
                reference=data.get("reference", ""), paid_to=data.get("paid_to"),
                actor=request.user,
            )
        except CreditError as exc:
            return _error(exc)
        return Response(DepositSettlementSerializer(self.get_queryset().get(pk=settlement.pk)).data)

    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        settlement = self.get_object()
        ser = ReasonSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            service.void_settlement(settlement, reason=ser.validated_data["reason"], actor=request.user)
        except CreditError as exc:
            return _error(exc)
        return Response(DepositSettlementSerializer(self.get_queryset().get(pk=settlement.pk)).data)

    @action(detail=True, methods=["get"])
    def statement(self, request, pk=None):
        from .pdf_service import render_to_pdf

        settlement = self.get_object()
        pdf = render_to_pdf("payments/deposit_settlement_pdf.html", statement_context(settlement))
        if pdf is None:
            return Response(
                {"detail": "The settlement statement could not be generated."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="deposit-settlement-{settlement.number}.pdf"'
        return response
