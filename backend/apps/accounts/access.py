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

#: A permission that only works with another one on: recording money is
#: no use to someone who can't see the books. Taking the second away takes
#: the first with it.
REQUIRES: dict[str, frozenset[str]] = {
    Cap.RECORD_MONEY: frozenset({Cap.VIEW_FINANCE}),
    Cap.FORGIVE_MONEY: frozenset({Cap.VIEW_FINANCE}),
    Cap.SEND_MESSAGES: frozenset({Cap.VIEW_FINANCE}),
    Cap.MANAGE_PROPERTY: frozenset({Cap.VIEW_PROPERTY}),
    Cap.RECORD_WATER: frozenset({Cap.VIEW_PROPERTY}),
    Cap.LOG_MAINTENANCE: frozenset({Cap.VIEW_PROPERTY}),
}

#: Only the superadmin may give these to someone whose role lacks them:
#: running the accounts, and writing money off.
SUPERADMIN_GRANTS = frozenset({Cap.MANAGE_USERS, Cap.FORGIVE_MONEY})

#: What the Access dialog lists, in order: (capability, area, label, what it allows).
PERMISSIONS: list[tuple[str, str, str, str]] = [
    (Cap.VIEW_FINANCE, "Money", "See the books",
     "Dashboard, payments, arrears, expenses, income and reports."),
    (Cap.RECORD_MONEY, "Money", "Record money",
     "Record and edit payments, expenses, income and charges; reconcile."),
    (Cap.FORGIVE_MONEY, "Money", "Void and write off",
     "Void payments, waive arrears, give credits and refunds, settle deposits."),
    (Cap.VIEW_PROPERTY, "Properties", "See properties",
     "Buildings, units, tenants and maintenance."),
    (Cap.MANAGE_PROPERTY, "Properties", "Manage properties",
     "Add and edit buildings and units; move tenants in and out; KYC."),
    (Cap.RECORD_WATER, "Water", "Record meter readings", "Capture water readings."),
    (Cap.LOG_MAINTENANCE, "Maintenance", "Log maintenance", "Raise and update maintenance requests."),
    (Cap.SEND_MESSAGES, "Messages", "Send messages", "SMS reminders and emailed statements."),
    (Cap.VIEW_ACTIVITY, "Activity", "See the activity log", "Who did what, and when."),
    (Cap.MANAGE_USERS, "Users", "Manage users", "Invite people, change their access, switch accounts off."),
]
LABELS = {cap: label for cap, _area, label, _hint in PERMISSIONS}


def effective(role: str, added=(), removed=()) -> frozenset[str]:
    """The role's capabilities, with this person's own changes applied.

    A building-limited role can only lose capabilities: anything it gained
    would reach records outside its buildings, which the scoping doesn't cover.
    A capability whose requirement is gone goes too.
    """
    base = ROLE_CAPABILITIES.get(role, frozenset())
    extra = frozenset() if role in SCOPED_ROLES else frozenset(added or ())
    caps = set((base | extra) - frozenset(removed or ())) & Cap.ALL
    changed = True
    while changed:
        changed = False
        for cap in list(caps):
            if not REQUIRES.get(cap, frozenset()) <= caps:
                caps.discard(cap)
                changed = True
    return frozenset(caps)


def capabilities(user) -> frozenset[str]:
    if not user or not getattr(user, "is_authenticated", False):
        return frozenset()
    if user.is_superuser:
        return Cap.ALL
    return effective(
        user.role,
        getattr(user, "extra_capabilities", None) or (),
        getattr(user, "removed_capabilities", None) or (),
    )


def grantable(actor) -> frozenset[str]:
    """What ``actor`` may give someone beyond their role: only what they hold
    themselves, and never the superadmin's own grants."""
    if actor.is_superuser:
        return Cap.ALL
    mine = capabilities(actor)
    if Cap.MANAGE_USERS not in mine:
        return frozenset()
    return mine - SUPERADMIN_GRANTS


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
    # The roster export is a list of balances.
    (r"^tenants/export/", Cap.VIEW_FINANCE, Cap.VIEW_FINANCE),
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
