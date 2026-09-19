"""Serializers for tenant credits and refunds (see ``credits.py``)."""
import datetime as _dt
from decimal import Decimal

from rest_framework import serializers

from apps.expenses.models import ExpenseCategory
from apps.tenants.models import Tenant

from .models import (
    Arrears,
    CreditReason,
    PaymentSource,
    Refund,
    TenantCredit,
    UtilityCharge,
)


def _user_name(user) -> str:
    if user is None:
        return ""
    return user.get_full_name() or user.get_username()


def _period_label(month: int, year: int) -> str:
    try:
        return _dt.date(year, month, 1).strftime("%B %Y")
    except ValueError:
        return f"{month}/{year}"


class TenantCreditSerializer(serializers.ModelSerializer):
    credit_type_display = serializers.CharField(source="get_credit_type_display", read_only=True)
    reason_display = serializers.CharField(source="get_reason_display", read_only=True)
    status_display = serializers.SerializerMethodField()
    remaining = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    is_void = serializers.BooleanField(read_only=True)
    has_evidence = serializers.SerializerMethodField()
    corrects = serializers.SerializerMethodField()
    expense_category_name = serializers.CharField(source="expense_category.name", read_only=True, default="")
    created_by_name = serializers.SerializerMethodField()
    approved_by_name = serializers.SerializerMethodField()
    voided_by_name = serializers.SerializerMethodField()
    history = serializers.SerializerMethodField()

    class Meta:
        model = TenantCredit
        fields = [
            "id", "number", "tenant", "credit_type", "credit_type_display",
            "reason", "reason_display", "credit_date",
            "net_amount", "vat_amount", "amount",
            "amount_applied", "amount_refunded", "remaining",
            "status", "status_display", "is_void", "on_hold",
            "description", "internal_notes", "reference",
            "has_evidence", "evidence_name", "corrects",
            "expense_category", "expense_category_name",
            "created_by_name", "created_at", "approved_by_name", "approved_at", "approval_mode",
            "voided_at", "voided_by_name", "void_reason",
            "history",
        ]

    def get_status_display(self, obj) -> str:
        if obj.is_void:
            return "Void"
        if obj.remaining <= 0:
            return "Fully used"
        if obj.on_hold:
            return "Held"
        if obj.amount_applied or obj.amount_refunded:
            return "Partly used"
        return "Available"

    def get_has_evidence(self, obj) -> bool:
        return bool(obj.evidence)

    def get_corrects(self, obj) -> str:
        if obj.arrears_id:
            return f"Rent {_period_label(obj.arrears.period_month, obj.arrears.period_year)}"
        if obj.utility_charge_id:
            return obj.utility_charge.description()
        return ""

    def get_created_by_name(self, obj) -> str:
        return _user_name(obj.created_by)

    def get_approved_by_name(self, obj) -> str:
        return _user_name(obj.approved_by)

    def get_voided_by_name(self, obj) -> str:
        return _user_name(obj.voided_by)

    def get_history(self, obj) -> list[dict]:
        """Credit History: every event in the credit's life, in plain words, oldest first."""
        events = [{
            "at": obj.created_at,
            "date": obj.credit_date,
            "kind": "issued",
            "text": f"Credit added by {_user_name(obj.created_by) or 'system'} — {obj.get_reason_display()}",
            "amount": obj.amount,
        }]
        for app in obj.applications.all():
            period = _period_label(app.arrears.period_month, app.arrears.period_year)
            how = " (automatic)" if app.origin != "owner" else ""
            events.append({
                "at": app.created_at, "date": app.applied_on, "kind": "applied",
                "text": f"Applied to {period} rent{how}", "amount": app.amount,
            })
            if app.reversed_at:
                events.append({
                    "at": app.reversed_at, "date": app.reversed_at.date(), "kind": "unapplied",
                    "text": f"Taken back off {period} rent — {app.reverse_reason}", "amount": app.amount,
                })
        for line in obj.refund_lines.all():
            refund = line.refund
            events.append({
                "at": refund.created_at, "date": refund.sent_on or refund.created_at.date(),
                "kind": "refund",
                "text": f"{refund.number}: {refund.get_status_display()} by {refund.get_method_display()}"
                        + (f", ref {refund.reference}" if refund.reference else ""),
                "amount": line.amount,
            })
        if obj.voided_at:
            events.append({
                "at": obj.voided_at, "date": obj.voided_at.date(), "kind": "void",
                "text": f"Voided by {_user_name(obj.voided_by) or 'system'} — {obj.void_reason}",
                "amount": obj.amount,
            })
        events.sort(key=lambda e: e["at"])
        return events


class CreditCreateSerializer(serializers.Serializer):
    tenant = serializers.PrimaryKeyRelatedField(queryset=Tenant.objects.all())
    reason = serializers.ChoiceField(choices=CreditReason.choices)
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0.01"))
    credit_date = serializers.DateField()
    description = serializers.CharField(max_length=200)
    internal_notes = serializers.CharField(required=False, allow_blank=True, default="")
    reference = serializers.CharField(required=False, allow_blank=True, default="", max_length=100)
    arrears = serializers.PrimaryKeyRelatedField(queryset=Arrears.objects.all(), required=False, allow_null=True)
    utility_charge = serializers.PrimaryKeyRelatedField(
        queryset=UtilityCharge.objects.all(), required=False, allow_null=True,
    )
    expense_category = serializers.PrimaryKeyRelatedField(
        queryset=ExpenseCategory.objects.all(), required=False, allow_null=True,
    )
    evidence = serializers.FileField(required=False, allow_null=True)
    hold = serializers.BooleanField(required=False, default=False)


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255)


class HoldSerializer(serializers.Serializer):
    hold = serializers.BooleanField()


class RefundLineSerializer(serializers.Serializer):
    source = serializers.SerializerMethodField()
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)

    def get_source(self, obj) -> str:
        return obj.credit.number if obj.credit_id else "Overpaid rent"


class RefundSerializer(serializers.ModelSerializer):
    method_display = serializers.CharField(source="get_method_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    lines = RefundLineSerializer(many=True, read_only=True)
    created_by_name = serializers.SerializerMethodField()
    sent_recorded_by_name = serializers.SerializerMethodField()
    closed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Refund
        fields = [
            "id", "number", "tenant", "amount", "method", "method_display",
            "paid_to", "reference", "notes", "status", "status_display", "sent_on",
            "lines", "created_by_name", "created_at", "approval_mode",
            "sent_recorded_by_name", "sent_recorded_at",
            "closed_by_name", "closed_at", "close_reason",
        ]

    def get_created_by_name(self, obj) -> str:
        return _user_name(obj.created_by)

    def get_sent_recorded_by_name(self, obj) -> str:
        return _user_name(obj.sent_recorded_by)

    def get_closed_by_name(self, obj) -> str:
        return _user_name(obj.closed_by)


class RefundCreateSerializer(serializers.Serializer):
    tenant = serializers.PrimaryKeyRelatedField(queryset=Tenant.objects.all())
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0.01"))
    method = serializers.ChoiceField(choices=PaymentSource.choices)
    paid_to = serializers.CharField(required=False, allow_blank=True, default="", max_length=100)
    reference = serializers.CharField(required=False, allow_blank=True, default="", max_length=100)
    notes = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)
    already_sent = serializers.BooleanField()
    sent_on = serializers.DateField(required=False, allow_null=True)
    credit = serializers.PrimaryKeyRelatedField(
        queryset=TenantCredit.objects.all(), required=False, allow_null=True,
    )

    def validate(self, attrs):
        if attrs["already_sent"] and not attrs.get("sent_on"):
            raise serializers.ValidationError({"sent_on": "Enter the date the money was sent."})
        return attrs


class MarkSentSerializer(serializers.Serializer):
    sent_on = serializers.DateField()
    reference = serializers.CharField(required=False, allow_blank=True, default="", max_length=100)
    method = serializers.ChoiceField(choices=PaymentSource.choices, required=False)
    paid_to = serializers.CharField(required=False, allow_blank=True, max_length=100)

