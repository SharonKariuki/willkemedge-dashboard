"""Financial audit trail — one helper, used everywhere money moves.

Kept deliberately tiny and dependency-free so it can be called from services,
views, admin actions and management commands without import cycles.

Recording an audit row must never be the reason a legitimate financial action
fails, so `record()` swallows its own errors (and logs them) rather than
propagating. The action it describes has already been validated by its caller.
"""
import logging
from decimal import Decimal

logger = logging.getLogger(__name__)


def _jsonable(value):
    """Coerce a field value into something JSONField can store losslessly."""
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def record(
    *,
    action: str,
    object_type: str,
    object_id: int | None,
    summary: str,
    actor=None,
    old_values: dict | None = None,
    new_values: dict | None = None,
) -> None:
    """Append one row to the financial audit log.

    `actor` may be a User, an AnonymousUser, or None (system/automated action).
    """
    from .models import FinancialAuditLog

    try:
        user = actor if getattr(actor, "is_authenticated", False) else None
        FinancialAuditLog.objects.create(
            actor=user,
            action=action,
            object_type=object_type,
            object_id=object_id,
            summary=summary[:255],
            old_values={k: _jsonable(v) for k, v in (old_values or {}).items()},
            new_values={k: _jsonable(v) for k, v in (new_values or {}).items()},
        )
    except Exception:  # noqa: BLE001 — auditing must not break the action it records
        logger.exception("audit: failed to record %s on %s#%s", action, object_type, object_id)
