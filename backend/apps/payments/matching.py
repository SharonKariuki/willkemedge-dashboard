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

from apps.buildings.models import Unit
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


def match_tenant(bill_ref: str) -> Tenant | None:
    """Match a (normalised) BillRefNumber to the active tenant on that unit.

    Returns None when:
      - the normalised ref is empty
      - no Unit has that label
      - more than one Unit shares that label across buildings (ambiguous —
        we refuse to silently guess which one; the event lands in the
        UNMATCHED queue for admin review). Today's seed data has no
        collisions, but a future building could introduce one.
    """
    house_number = normalize_bill_ref(bill_ref)
    if not house_number:
        return None
    units = list(Unit.objects.filter(label__iexact=house_number)[:2])
    if not units:
        return None
    if len(units) > 1:
        # Ambiguous — multiple buildings share this label. Caller will
        # treat the event as UNMATCHED so an admin can disambiguate.
        return None
    return Tenant.objects.filter(unit=units[0], status=TenantStatus.ACTIVE).first()


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
