"""
Tenant payment-matching helpers.

Pure functions that map an inbound payment's bill reference or payer phone to
the active tenant on a unit. No external API calls — safe to use from any
ingestion path (Co-op IPN, manual entry, future bank feeds).

`match_tenant` normalises a BillRefNumber by stripping the configured
MPESA_ACCOUNT_PREFIX and any leading separator, leaving a bare house number
that must equal a Unit.label.
"""
import re

from django.conf import settings

from apps.buildings.models import Unit, UnitAlias
from apps.tenants.models import Tenant, TenantStatus

# Separators a payer might type between the account prefix and house number
# (e.g. "90290#A12", "90290 A12", "90290-A12").
_BILL_REF_SEP_RE = re.compile(r"^[\s#*\-./]+")


def normalize_bill_ref(bill_ref: str) -> str:
    """Recover the bare house number from a Paybill BillRefNumber.

    Strips the configured MPESA_ACCOUNT_PREFIX and any leading separator. A
    payer who typed just the house number ("A12") still works.
    """
    ref = (bill_ref or "").strip().upper()
    prefix = str(getattr(settings, "MPESA_ACCOUNT_PREFIX", "") or "").strip().upper()
    if prefix and ref.startswith(prefix):
        ref = ref[len(prefix):]
    return _BILL_REF_SEP_RE.sub("", ref).strip()


def _unit_for_label(house_number: str) -> Unit | None:
    """Resolve a bare label to a single Unit, or None if absent/ambiguous.

    Tries the current `Unit.label` first, then falls back to retired labels in
    `UnitAlias` so payments that still use the OLD account reference keep
    matching during the building-code transition. A global unique constraint
    keeps both label and alias namespaces unambiguous, so this returns at most
    one unit; the `[:2]` guard is belt-and-braces in case the constraint is not
    yet deployed.
    """
    units = list(Unit.objects.filter(label__iexact=house_number)[:2])
    if len(units) == 1:
        return units[0]
    if len(units) > 1:
        return None  # ambiguous — let the caller queue it for admin review
    aliases = list(UnitAlias.objects.filter(label__iexact=house_number).select_related("unit")[:2])
    if len(aliases) == 1:
        return aliases[0].unit
    return None


def match_tenant(bill_ref: str) -> Tenant | None:
    """Match a (normalised) BillRefNumber to the active tenant on that unit.

    Returns None when:
      - the normalised ref is empty
      - no Unit (or retired alias) has that label
      - more than one Unit shares that label across buildings (ambiguous —
        we refuse to silently guess which one; the event lands in the
        UNMATCHED queue for admin review). The global unique-label constraint
        makes genuine collisions impossible once deployed.
    """
    house_number = normalize_bill_ref(bill_ref)
    if not house_number:
        return None
    unit = _unit_for_label(house_number)
    if unit is None:
        return None
    return Tenant.objects.filter(unit=unit, status=TenantStatus.ACTIVE).first()


def normalize_msisdn(phone: str | int) -> str:
    """Reduce any Kenyan phone format to bare digits starting with 254."""
    digits = "".join(c for c in str(phone) if c.isdigit())
    if digits.startswith("0"):
        digits = "254" + digits[1:]
    return digits


def tenant_by_phone(msisdn: str) -> Tenant | None:
    """Find the active tenant whose stored phone matches the payer MSISDN.

    NOTE: O(n) scan over active tenants. Acceptable at current scale; replace
    with a stored normalised-phone column + indexed lookup if the portfolio
    grows large (see review item M2).
    """
    target = normalize_msisdn(msisdn)
    if not target:
        return None
    for tenant in Tenant.objects.filter(status=TenantStatus.ACTIVE):
        if normalize_msisdn(tenant.phone) == target:
            return tenant
    return None
