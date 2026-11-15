"""Who may do what: capabilities, the roles that bundle them, and which
buildings a caretaker sees.

Code asks "may this person record money?", never "is this person an
accountant?". A role is a named bundle of capabilities, so a new role later is
one more entry in ``ROLE_CAPABILITIES`` rather than a hunt through every view.

The API enforces this in one place - :class:`apps.accounts.authentication.
AccessPolicyAuthentication` checks every signed-in request against
:func:`required_capability` before the view runs. A route not listed falls to
the strictest rule (financial), so an endpoint added later is locked until it
is placed here, rather than open until someone remembers.

Views keep their own finer checks on top (only the owner voids a payment, for
example); this is the floor, not the whole house.
"""
from __future__ import annotations

import re


class Cap:
    VIEW_FINANCE = "view_finance"          # payments, arrears, ledger, reports, expenses, dashboard
    RECORD_MONEY = "record_money"          # record payments, expenses, income, charges, reconcile
    FORGIVE_MONEY = "forgive_money"        # void, waive, credits, refunds, deposit settlements
    VIEW_PROPERTY = "view_property"        # buildings, units, tenants, maintenance
    MANAGE_PROPERTY = "manage_property"    # add/edit buildings and units, move tenants in and out, KYC
    RECORD_WATER = "record_water"          # meter readings
    LOG_MAINTENANCE = "log_maintenance"    # raise and update maintenance requests
    SEND_MESSAGES = "send_messages"        # SMS reminders, emailed statements
    VIEW_ACTIVITY = "view_activity"        # the activity log
    MANAGE_USERS = "manage_users"          # invite, change roles, switch accounts off

    ALL = frozenset({
        VIEW_FINANCE, RECORD_MONEY, FORGIVE_MONEY, VIEW_PROPERTY, MANAGE_PROPERTY,
        RECORD_WATER, LOG_MAINTENANCE, SEND_MESSAGES, VIEW_ACTIVITY, MANAGE_USERS,
    })


ROLE_CAPABILITIES: dict[str, frozenset[str]] = {
    "owner": Cap.ALL,
    "accountant": frozenset({
        Cap.VIEW_FINANCE, Cap.RECORD_MONEY, Cap.VIEW_PROPERTY, Cap.MANAGE_PROPERTY,
        Cap.RECORD_WATER, Cap.LOG_MAINTENANCE, Cap.SEND_MESSAGES,
    }),
    # Reads everything, including who did what; changes nothing.
    "auditor": frozenset({Cap.VIEW_FINANCE, Cap.VIEW_PROPERTY, Cap.VIEW_ACTIVITY}),
    "viewer": frozenset({Cap.VIEW_FINANCE, Cap.VIEW_PROPERTY}),
    # Their own buildings only (see ``scope``): the tenants and units there,
    # meter readings and maintenance. No ledgers, payments or reports.
    "caretaker": frozenset({Cap.VIEW_PROPERTY, Cap.RECORD_WATER, Cap.LOG_MAINTENANCE}),
}

#: Roles whose view of the portfolio is limited to their assigned buildings.
SCOPED_ROLES = frozenset({"caretaker"})


def capabilities(user) -> frozenset[str]:
    if not user or not getattr(user, "is_authenticated", False):
        return frozenset()
    if user.is_superuser:
        return Cap.ALL
    return ROLE_CAPABILITIES.get(user.role, frozenset())


def has_capability(user, capability: str) -> bool:
    return capability in capabilities(user)


# ── Buildings ───────────────────────────────────────────────────────────────

def is_scoped(user) -> bool:
    return bool(user and not user.is_superuser and user.role in SCOPED_ROLES)


def scope(queryset, user, building_path: str):
    """``queryset`` narrowed to the buildings ``user`` may see.

    ``building_path`` is the lookup from the model to its Building ("pk" for
    buildings themselves, "building" for units, "unit__building" for tenants).
    A caretaker with no buildings assigned sees nothing.
    """
    if not is_scoped(user):
        return queryset
    field = "pk" if building_path == "pk" else f"{building_path}_id"
    return queryset.filter(**{f"{field}__in": user.buildings.values("pk")})


# ── Routes ──────────────────────────────────────────────────────────────────

# (pattern on the path after /api/, capability to read, capability to write).
# A capability may be a tuple: any one of them is enough. First match wins.
# ``None`` leaves the route to the view's own permissions (sign-in, the
# machine-to-machine bank and cron endpoints, which carry their own secrets).
RULES: list[tuple[re.Pattern, object, object]] = [(re.compile(p), r, w) for p, r, w in [
    (r"^(auth|health)/", None, None),
    (r"^payments/(coop|cron)/", None, None),
    # A tenant's money is financial even on the tenant record.
    (r"^tenants/[^/]+/(payment-history|statement-pdf)/", Cap.VIEW_FINANCE, Cap.VIEW_FINANCE),
    (r"^tenants/([^/]+/)?email-statements?/", Cap.VIEW_FINANCE, Cap.SEND_MESSAGES),
    (r"^(buildings|units|tenants)/", Cap.VIEW_PROPERTY, Cap.MANAGE_PROPERTY),
    (r"^maintenance/", Cap.VIEW_PROPERTY, Cap.LOG_MAINTENANCE),
    # Meter readings: the caretaker's job, and the accountant's.
    (r"^utility-charges/(reading|previous-reading)/", Cap.RECORD_WATER, Cap.RECORD_WATER),
    (r"^utility-charges/$", (Cap.VIEW_FINANCE, Cap.RECORD_WATER), Cap.RECORD_MONEY),
    (r"^notifications/", Cap.VIEW_FINANCE, Cap.SEND_MESSAGES),
    # Downloading a report is reading it, though the browser POSTs the table.
    (r"^reports/export/", Cap.VIEW_FINANCE, Cap.VIEW_FINANCE),
    # Everything else is money: read to look, record to change.
    (r"", Cap.VIEW_FINANCE, Cap.RECORD_MONEY),
]]

READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def required_capability(path: str, method: str):
    """The capability (or tuple of alternatives) a request needs, or None."""
    rel = re.sub(r"^/?api/", "", path or "")
    for pattern, read, write in RULES:
        if pattern.match(rel):
            return read if method.upper() in READ_METHODS else write
    return Cap.VIEW_FINANCE  # unreachable: the last rule matches everything


def allowed(user, need) -> bool:
    if need is None:
        return True
    options = need if isinstance(need, tuple) else (need,)
    caps = capabilities(user)
    return any(o in caps for o in options)


REFUSALS = {
    Cap.VIEW_FINANCE: "Your role doesn't include the financial records.",
    Cap.RECORD_MONEY: "Your role can't record or change money.",
    Cap.FORGIVE_MONEY: "Only the owner/director can void or write off money.",
    Cap.VIEW_PROPERTY: "Your role doesn't include the property records.",
    Cap.MANAGE_PROPERTY: "Your role can't change buildings, units or tenants.",
    Cap.RECORD_WATER: "Your role can't record meter readings.",
    Cap.LOG_MAINTENANCE: "Your role can't log maintenance.",
    Cap.SEND_MESSAGES: "Your role can't send messages or statements.",
    Cap.VIEW_ACTIVITY: "Your role doesn't include the activity log.",
    Cap.MANAGE_USERS: "Only the owner or the superadmin can manage users.",
}


def refusal(need) -> str:
    first = need[0] if isinstance(need, tuple) else need
    return REFUSALS.get(first, "Your role doesn't allow this.")
