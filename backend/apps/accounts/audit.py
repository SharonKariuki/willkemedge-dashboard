"""Audit trail — one helper, used everywhere something worth answering for happens.

Kept deliberately small and cheap to import so it can be called from services,
views, admin actions and management commands without import cycles.

Callers say *what* happened. Who did it, from which device, in which sign-in
and through which door (dashboard, bank notification, scheduled job, server
command) is filled in from `audit_context`, which the entry points open.

Recording an audit row must never be the reason a legitimate action fails, so
`record()` swallows its own errors (and logs them) rather than propagating.
The action it describes has already been validated by its caller.
"""
import logging
from decimal import Decimal

from .audit_context import Source, current

logger = logging.getLogger(__name__)

#: Action prefixes that move or change money. Used when a caller does not say.
FINANCIAL_PREFIXES = (
    "payment.", "arrears.", "credit.", "refund.", "expense.", "manual_income.",
    "utility_charge.", "tenant.deposit", "billing.",
)


def _jsonable(value):
    """Coerce a field value into something JSONField can store losslessly."""
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def actor_label(user) -> str:
    full = f"{user.first_name} {user.last_name}".strip()
    return full or user.email


def _request_fields(request) -> dict:
    """IP, device and sign-in session from the request, when there is one."""
    if request is None:
        return {}
    from .services import get_client_ip, get_user_agent

    session_id = ""
    # A dashboard request carries the JWT DRF validated; its `sid` claim is set
    # once at sign-in and survives every refresh (see LoginSerializer).
    token = getattr(request, "auth", None)
    if token is not None and hasattr(token, "get"):
        session_id = str(token.get("sid", "") or "")
    elif getattr(request, "session", None) is not None:
        # The Django admin signs in with a cookie session instead.
        session_id = request.session.session_key or ""
    return {
        "ip_address": get_client_ip(request),
        "user_agent": get_user_agent(request)[:255],
        "session_id": session_id[:32],
    }


def _command_line(argv: list[str]) -> str:
    """The command as typed, with long arguments (a `shell -c` script) cut short."""
    parts = [" ".join(a.split()) for a in argv]
    return " ".join(p if len(p) <= 40 else p[:39] + "…" for p in parts)


def _resolve_actor(actor, request):
    if getattr(actor, "is_authenticated", False):
        return actor
    user = getattr(request, "user", None)
    if getattr(user, "is_authenticated", False):
        return user
    return None


def _write(**fields):
    from django.db import transaction

    from .models import AuditLog

    # A savepoint, so a failed insert cannot poison the caller's transaction:
    # on Postgres the next query would otherwise fail with "current
    # transaction is aborted" and take the audited action down with it.
    with transaction.atomic():
        return AuditLog.objects.create(**fields)


#: Actions that undo an entry. When the person undoing it is the one who made
#: it, the row says so, so the director can see it without anyone being
#: blocked: with one director, a second approver is not always there.
REVERSALS = frozenset({
    "payment.void", "credit.void", "refund.cancel", "refund.void",
    "tenant.deposit_settlement_void",
    "payment.delete", "utility_charge.delete", "expense.delete", "manual_income.delete",
    "expense.void", "manual_income.void",
})

#: Where the entry's maker is kept, for entries whose creation is not itself
#: a logged ".create" row.
_MAKER_MODELS = {
    "payment": "payments.Payment",
    "tenant_credit": "payments.TenantCredit",
    "refund": "payments.Refund",
    "deposit_settlement": "payments.DepositSettlement",
    "utility_charge": "payments.UtilityCharge",
}


def _maker_id(object_type: str, object_id: int):
    """Who made the entry: its created_by, else the actor of its ".create" row."""
    from django.apps import apps

    from .models import AuditLog

    label = _MAKER_MODELS.get(object_type)
    if label:
        model = apps.get_model(label)
        maker = model.objects.filter(pk=object_id).values_list("created_by_id", flat=True).first()
        if maker:
            return maker
    return (
        AuditLog.objects.filter(
            object_type=object_type, object_id=object_id, action=f"{object_type}.create"
        )
        .order_by("id")
        .values_list("actor_id", flat=True)
        .first()
    )


def _is_own_entry(action: str, object_type: str, object_id, user) -> bool:
    if action not in REVERSALS or not object_id or not getattr(user, "pk", None):
        return False
    try:
        return _maker_id(object_type, object_id) == user.pk
    except Exception:  # noqa: BLE001 — the flag is a courtesy, never a failure
        logger.exception("audit: could not find who made %s#%s", object_type, object_id)
        return False


def record(
    *,
    action: str,
    object_type: str,
    object_id: int | None,
    summary: str,
    actor=None,
    old_values: dict | None = None,
    new_values: dict | None = None,
    kind: str = "event",
    object_label: str = "",
    is_financial: bool | None = None,
    session_id: str | None = None,
):
    """Append one row to the audit log. Returns it, or None if writing failed.

    `actor` may be a User, an AnonymousUser, or None. When it is not a signed-in
    user, whoever is signed in on the current request is used instead; a row
    with neither is a system action.
    """
    try:
        ctx = current()
        request = ctx.request
        user = _resolve_actor(actor, request)
        if is_financial is None:
            is_financial = action.startswith(FINANCIAL_PREFIXES)

        common = {
            "actor": user,
            "actor_label": actor_label(user) if user else "",
            # The superadmin is labelled as such, not by the role field
            # their account happens to carry.
            "actor_role": (
                "superadmin" if getattr(user, "is_superuser", False)
                else getattr(user, "role", "")
            ) if user else "",
            "source": ctx.source,
            "source_detail": ctx.source_detail[:120],
            "request_id": ctx.request_id,
            **_request_fields(request),
        }
        if session_id is not None:
            # Sign-in happens before the request carries a token to read it from.
            common["session_id"] = session_id[:32]

        if ctx.source == Source.COMMAND and not ctx.announced:
            # A server command is announced once, on its first audited write,
            # so the log says which command ran — `--apply` and all — before
            # the changes it made. A command that changes nothing never shows.
            ctx.announced = True
            _write(
                **common,
                kind="event",
                action="command.run",
                object_type="command",
                object_id=None,
                object_label=ctx.source_detail[:150],
                summary=f"Server command run: manage.py {_command_line(ctx.argv)}"[:255],
                is_financial=False,
            )

        new_values = dict(new_values or {})
        if _is_own_entry(action, object_type, object_id, user):
            new_values["self_reversal"] = True
            summary = f"{summary} (their own entry)"

        return _write(
            **common,
            kind=kind,
            action=action,
            object_type=object_type,
            object_id=object_id,
            object_label=object_label[:150],
            summary=summary[:255],
            old_values={k: _jsonable(v) for k, v in (old_values or {}).items()},
            new_values={k: _jsonable(v) for k, v in (new_values or {}).items()},
            is_financial=is_financial,
        )
    except Exception:  # noqa: BLE001 — auditing must not break the action it records
        logger.exception("audit: failed to record %s on %s#%s", action, object_type, object_id)
        return None
