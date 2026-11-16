"""DRF permission classes, each one capability from ``apps.accounts.access``.

Every request already passes the central policy (``AccessPolicyAuthentication``),
which maps each route to the capability it needs and refuses the rest. These
classes sit on the views and actions that need more than their route's rule -
voiding a payment is a POST under ``payments/`` (record money) but takes the
write-off capability - so the finer check is written where the action is.

They ask for a capability, never a role, so a person's own changes to their
role count here exactly as they do in the policy.
"""
from rest_framework.permissions import SAFE_METHODS, BasePermission

from .access import Cap, has_capability


class _CapabilityForWrites(BasePermission):
    """Reads pass (the route's own rule governs them); writes need ``capability``."""

    capability: str = ""

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        return has_capability(request.user, self.capability)


class CanRecordMoney(_CapabilityForWrites):
    """Create or change financial records: payments, bank-credit reconciliation."""

    capability = Cap.RECORD_MONEY
    message = "Your access doesn't include recording money."


class CanForgiveMoney(_CapabilityForWrites):
    """Write debt off or unwind money: waivers, voids, credits, refunds, deposit settlements."""

    capability = Cap.FORGIVE_MONEY
    message = "Only the owner/director may void, waive or write money off."


class CanViewActivity(BasePermission):
    """The activity log: owner, superadmin and auditor, or anyone given it.

    It names who did what to whom, including other staff's sign-ins, so it is
    not "read for everyone" like the money pages.
    """

    message = "Your access doesn't include the activity log."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and has_capability(user, Cap.VIEW_ACTIVITY))


#: The old name, kept so imports keep working; it was never about the owner as such.
IsOwner = CanViewActivity
