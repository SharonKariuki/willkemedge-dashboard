"""
Notification API — list templates, send to one/many tenants, view history.
"""
from decimal import Decimal, InvalidOperation

from django.conf import settings
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.tenants.models import Tenant, TenantStatus

from .models import (
    Arrears,
    NotificationChannel,
    TenantNotification,
)
from .notification_services import dispatch_notification
from .notification_templates import TEMPLATES
from .notifications import fetch_sms_balance


class TenantNotificationSerializer(serializers.ModelSerializer):
    tenant_name = serializers.CharField(source="tenant.full_name", read_only=True)
    unit_label = serializers.CharField(source="tenant.unit.label", read_only=True)
    channel_display = serializers.CharField(source="get_channel_display", read_only=True)

    class Meta:
        model = TenantNotification
        fields = [
            "id",
            "tenant",
            "tenant_name",
            "unit_label",
            "channel",
            "channel_display",
            "subject",
            "body",
            "status",
            "sent_at",
            "error",
            "template_key",
            "created_at",
        ]
        read_only_fields = fields


class SendNotificationSerializer(serializers.Serializer):
    """Input for POST /api/notifications/send/."""

    AUDIENCE_CHOICES = [
        ("tenant", "Single / multiple tenants"),
        ("all_active", "All active tenants"),
        ("with_arrears", "Tenants with open arrears"),
    ]

    audience = serializers.ChoiceField(choices=AUDIENCE_CHOICES, default="tenant")
    tenant_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        allow_empty=True,
        default=list,
    )
    channel = serializers.ChoiceField(
        choices=NotificationChannel.choices, default=NotificationChannel.SMS
    )
    subject = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    body = serializers.CharField()
    template_key = serializers.CharField(
        max_length=50, required=False, allow_blank=True, default=""
    )

    def validate(self, attrs):
        if attrs["audience"] == "tenant" and not attrs.get("tenant_ids"):
            raise serializers.ValidationError(
                {"tenant_ids": "Select at least one tenant."}
            )
        if not attrs["body"].strip():
            raise serializers.ValidationError({"body": "Message body is required."})
        return attrs


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Manage outbound tenant notifications.

    Routes:
      GET  /api/notifications/            → history (most recent first)
      GET  /api/notifications/templates/  → built-in templates
      POST /api/notifications/send/       → compose + dispatch
    """

    permission_classes = [IsAuthenticated]
    serializer_class = TenantNotificationSerializer

    def get_queryset(self):
        qs = TenantNotification.objects.select_related(
            "tenant", "tenant__unit"
        )
        tenant_id = self.request.query_params.get("tenant")
        if tenant_id:
            qs = qs.filter(tenant_id=tenant_id)
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs[:200]

    @action(detail=False, methods=["get"], url_path="templates")
    def templates(self, request):
        return Response(TEMPLATES)

    @action(detail=False, methods=["get"], url_path="sms-balance")
    def sms_balance(self, request):
        """The Africa's Talking SMS wallet, plus how to top it up.

        Read-only by design: the director asked to see when airtime is running
        out, not to buy it from here. Topping up stays on M-Pesa (no STK push,
        no stored card), so the worst this endpoint can do is show a number.

        Never 502s on an AT outage — the top-up paybill is the half of the
        response that matters when the balance lookup is what's broken, so a
        failed lookup comes back 200 with ``balance: null`` and an ``error``.
        Pass ``?refresh=1`` to bypass the short server-side cache.
        """
        refresh = str(request.query_params.get("refresh", "")).lower() in ("1", "true", "yes")
        balance = fetch_sms_balance(refresh=refresh)

        threshold = _decimal_setting("AT_BALANCE_LOW_THRESHOLD", "500")
        amount = balance["balance"]

        return Response(
            {
                "configured": balance["configured"],
                "balance": str(amount) if amount is not None else None,
                "currency": balance["currency"] or "KES",
                "sms_remaining": balance["sms_remaining"],
                "unit_cost": str(balance["unit_cost"]),
                "low": amount is not None and amount < threshold,
                "low_threshold": str(threshold),
                "checked_at": balance["checked_at"],
                "cached": balance["cached"],
                "error": balance["error"],
                "topup": {
                    "paybill": str(getattr(settings, "AT_TOPUP_PAYBILL", "") or ""),
                    "account": str(getattr(settings, "AT_TOPUP_ACCOUNT", "") or ""),
                    "note": (
                        "M-Pesa → Lipa na M-Pesa → Pay Bill. The credit lands on the "
                        "Africa's Talking account that sends tenant SMS."
                    ),
                },
            }
        )

    @action(detail=False, methods=["post"], url_path="send")
    def send(self, request):
        serializer = SendNotificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        recipients = _resolve_recipients(
            audience=data["audience"],
            tenant_ids=data.get("tenant_ids", []),
        )
        if not recipients:
            return Response(
                {"detail": "No recipients matched."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        results = []
        for tenant in recipients:
            notification = TenantNotification.objects.create(
                tenant=tenant,
                channel=data["channel"],
                subject=data.get("subject", ""),
                body=data["body"],
                template_key=data.get("template_key", ""),
                created_by=request.user if request.user.is_authenticated else None,
            )
            # automatic=False: a person is sending this deliberately from the
            # dashboard, so it is not silenced by TENANT_NOTIFICATIONS_ENABLED.
            dispatch_notification(notification, automatic=False)
            results.append(notification)

        sent = sum(1 for n in results if n.status == "sent")
        failed = len(results) - sent

        return Response(
            {
                "sent": sent,
                "failed": failed,
                "total": len(results),
                "notifications": TenantNotificationSerializer(results, many=True).data,
            },
            status=status.HTTP_201_CREATED,
        )


def _resolve_recipients(audience: str, tenant_ids: list[int]):
    active = Tenant.objects.filter(status=TenantStatus.ACTIVE).select_related(
        "unit", "unit__building"
    )
    if audience == "all_active":
        return list(active)
    if audience == "with_arrears":
        owed_ids = Arrears.objects.filter(is_cleared=False).values_list(
            "tenant_id", flat=True
        )
        return list(active.filter(id__in=set(owed_ids)))
    return list(active.filter(id__in=tenant_ids))


def _decimal_setting(name: str, fallback: str) -> Decimal:
    """Read a money-ish setting as Decimal, tolerating a typo'd env var.

    These arrive from the environment as strings; a bad value must not 500 the
    one screen that tells the director his SMS credit is running out.
    """
    try:
        return Decimal(str(getattr(settings, name, fallback) or fallback))
    except (InvalidOperation, ValueError):
        return Decimal(fallback)
