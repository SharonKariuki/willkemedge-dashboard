"""
Notification API — list templates, send to one/many tenants, view history.
"""
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
            dispatch_notification(notification)
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
