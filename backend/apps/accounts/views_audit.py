"""GET /api/auth/activity/ — the director's activity log. Owner only.

Newest first, paged by id: pass the previous page's `next_before` as `before`.
Rows written by one request share a `request_id`, and the page groups them.

Filters (all optional, combinable):
    actor        user id, or "system" for rows nobody signed in wrote
    source       web | admin | bank | cron | command | system
    kind         event | change | auth | denied
    financial    "1" → only rows that move or change money
    date_from    YYYY-MM-DD, inclusive, Nairobi time
    date_to      YYYY-MM-DD, inclusive, Nairobi time
    q            text in the summary, the object's name or the person's name
    object_type  with object_id → one record's history
    session_id   everything done in one sign-in
    limit        page size, default 100, at most 200
"""
from datetime import date

from django.db.models import Q
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import AuditLog, User
from .permissions import IsOwner

DEFAULT_LIMIT = 100
MAX_LIMIT = 200


class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = (
            "id", "created_at", "kind", "action", "summary",
            "object_type", "object_id", "object_label", "old_values", "new_values",
            "is_financial", "actor", "actor_label", "actor_role",
            "source", "source_detail", "ip_address", "user_agent",
            "session_id", "request_id",
        )


def _date(value: str | None, name: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError({name: "Use YYYY-MM-DD."}) from exc


def _int(value: str | None, name: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ValidationError({name: "Must be a whole number."}) from exc


class ActivityLogView(APIView):
    permission_classes = [IsOwner]

    def get(self, request):
        p = request.query_params
        qs = AuditLog.objects.all()

        actor = p.get("actor")
        if actor == "system":
            qs = qs.filter(actor__isnull=True, actor_label="")
        elif actor:
            qs = qs.filter(actor_id=_int(actor, "actor"))
        for name in ("source", "kind", "object_type", "session_id"):
            if p.get(name):
                qs = qs.filter(**{name: p[name]})
        if p.get("object_id"):
            qs = qs.filter(object_id=_int(p["object_id"], "object_id"))
        if p.get("financial") in ("1", "true"):
            qs = qs.filter(is_financial=True)
        if d := _date(p.get("date_from"), "date_from"):
            qs = qs.filter(created_at__date__gte=d)
        if d := _date(p.get("date_to"), "date_to"):
            qs = qs.filter(created_at__date__lte=d)
        if q := (p.get("q") or "").strip():
            qs = qs.filter(
                Q(summary__icontains=q) | Q(object_label__icontains=q) | Q(actor_label__icontains=q)
            )
        if before := _int(p.get("before"), "before"):
            qs = qs.filter(id__lt=before)

        limit = min(_int(p.get("limit"), "limit") or DEFAULT_LIMIT, MAX_LIMIT)
        rows = list(qs.order_by("-id")[: limit + 1])
        more = len(rows) > limit
        rows = rows[:limit]

        body = {
            "results": AuditLogSerializer(rows, many=True).data,
            "next_before": rows[-1].id if more else None,
        }
        if not p.get("before"):
            # The people filter, sent once with the first page.
            body["people"] = [
                {
                    "id": u.id,
                    "label": f"{u.first_name} {u.last_name}".strip() or u.email,
                    "role": u.get_role_display(),
                }
                for u in User.objects.order_by("first_name", "email")
            ]
        return Response(body)
