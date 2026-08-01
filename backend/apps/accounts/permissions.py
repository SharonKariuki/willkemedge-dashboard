"""Role-based DRF permissions.

Every endpoint used to be `IsAuthenticated` and nothing more, so any account —
a caretaker, a data-entry clerk, a stolen session — could record payments, waive
arrears and reconcile bank credits. These classes restore segregation of duties:

    read money      → any authenticated user
    record money    → OWNER, ACCOUNTANT      (CanRecordMoney)
    forgive money   → OWNER only             (CanForgiveMoney)

Superusers always pass; they are the break-glass account.
"""
from rest_framework.permissions import SAFE_METHODS, BasePermission


class CanRecordMoney(BasePermission):
    """Create/modify financial records: payments, bank-credit reconciliation."""

    message = "Your role does not permit recording payments."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        return bool(getattr(request.user, "can_record_money", False))


class CanForgiveMoney(BasePermission):
    """Write debt off or unwind a receipt: waivers and voids. Owner only."""

    message = "Only the owner/director may waive arrears or void a payment."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        return bool(getattr(request.user, "can_forgive_money", False))
