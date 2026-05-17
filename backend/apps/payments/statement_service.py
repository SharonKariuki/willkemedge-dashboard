"""
Statement service — builds the full "Customer Rent Statement" payload.

This produces the data behind the rent statement PDF a tenant receives after
every payment (and that the admin can download from the tenant page). The
layout it feeds mirrors the official Wilkem rent statement:

  * branded header (entity name, address, contacts)
  * customer block (name, optional c/o, KRA PIN / ID / phone, unit descriptor)
  * statement summary box (Arrears/Others, Current Month, 16% VAT, Total Due)
  * payment options (M-Pesa Paybill + bank account)
  * a running-balance ledger of every rent charge, VAT line,
    utility (water/electricity) charge, and payment

Ledger rows are derived from stored records only:
  * Arrears        -> "Month Rent - <Mon>-<Year>"  (+ "16% VAT on Rent" for BUSINESS)
  * UtilityCharge  -> "<Label> <Mon. 'YY>" (+ multi-line readings if recorded)
  * Payment        -> "Payment Received"

Public API
----------
build_statement(tenant, *, statement_date=None, as_of=None) -> dict
"""
from __future__ import annotations

import datetime as _dt
from decimal import Decimal

from apps.buildings.models import UnitClassification

from .tax_service import calculate_tax

ZERO = Decimal("0.00")

# Project-wide fallbacks used when a Building has no per-building override.
DEFAULT_ENTITY_NAME = "Wilkem Edge Apartments"
DEFAULT_POSTAL_ADDRESS = "PO Box 66741 - 00800, Nairobi, Kenya"
DEFAULT_CONTACT_PHONE = "+254 722 527234 / +254 732 527234"
DEFAULT_CONTACT_EMAIL = "wilkem.ventures@gmail.com"


def _money(value) -> Decimal:
    return (Decimal(value) if value is not None else ZERO).quantize(Decimal("0.01"))


def _month_name(month: int, year: int) -> str:
    try:
        return f"{_dt.date(year, month, 1).strftime('%B')}-{year}"
    except ValueError:
        return f"{month}/{year}"


def _fmt_date(d) -> str:
    """'4 May 2026' — no leading zero, platform-independent."""
    if not hasattr(d, "strftime"):
        return str(d)
    return f"{d.day} {d.strftime('%b %Y')}"


def _fmt_money(value) -> str:
    """'23,350.00' — thousands-separated, 2 dp."""
    return f"{_money(value):,.2f}"


def _fmt_money_whole(value) -> str:
    """'102,960' when integer-valued, else '102,960.50'. Matches the sample TOTAL BALANCE DUE."""
    amt = _money(value)
    if amt == amt.to_integral_value():
        return f"{int(amt):,}"
    return f"{amt:,.2f}"


def _ordinal(n: int) -> str:
    """5 -> '5th', 1 -> '1st'."""
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _build_ledger(tenant, *, is_business: bool, as_of: _dt.date | None):
    """Return (rows, final_balance). Rows are dicts ready for the template."""
    from .models import Arrears, Payment, UtilityCharge

    # (posting_date, sort_order, description, invoice_amount, payment_amount)
    events: list[tuple[_dt.date, int, str, Decimal, Decimal]] = []

    for arr in Arrears.objects.filter(tenant=tenant).order_by("period_year", "period_month"):
        try:
            posting = _dt.date(arr.period_year, arr.period_month, 1)
        except ValueError:
            continue
        if as_of and posting > as_of:
            continue
        base = _money(arr.expected_rent)
        if is_business and base > 0:
            vat = calculate_tax(base, UnitClassification.BUSINESS).tax_amount
            events.append((posting, 0, f"Month Rent - {_month_name(arr.period_month, arr.period_year)}", base, ZERO))
            events.append((posting, 1, "16% VAT on Rent", _money(vat), ZERO))
        else:
            events.append((posting, 0, f"Month Rent - {_month_name(arr.period_month, arr.period_year)}", base, ZERO))

    for util in UtilityCharge.objects.filter(tenant=tenant).order_by("posting_date", "id"):
        if as_of and util.posting_date > as_of:
            continue
        events.append((util.posting_date, 2, util.description(), _money(util.amount), ZERO))

    for pay in Payment.objects.filter(tenant=tenant).order_by("payment_date", "created_at"):
        if as_of and pay.payment_date > as_of:
            continue
        events.append((pay.payment_date, 3, "Payment Received", ZERO, _money(pay.amount)))

    events.sort(key=lambda e: (e[0], e[1]))

    rows = []
    balance = ZERO
    for i, (posting, _order, desc, invoice, payment) in enumerate(events, start=1):
        balance = balance + invoice - payment
        rows.append({
            "index": i,
            "posting_date": _fmt_date(posting),
            "description": desc,
            "description_lines": desc.split("\n"),
            "invoice_amount": _fmt_money(invoice) if invoice else "",
            "payment": _fmt_money(payment) if payment else "",
            "balance": _fmt_money_whole(balance),
            "balance_negative": balance < 0,
        })
    return rows, balance


def _unit_descriptor(tenant) -> str:
    """Right-hand cell on the statement.

    Honors `Unit.statement_descriptor` when set; otherwise falls back to a
    sensible default ("Unit G05 — Building Name").
    """
    unit = tenant.unit
    explicit = getattr(unit, "statement_descriptor", "") or ""
    if explicit:
        return explicit
    return f"Unit {unit.label} — {unit.building.name}"


def build_statement(tenant, *, statement_date: _dt.date | None = None, as_of: _dt.date | None = None) -> dict:
    """
    Build the full rent-statement payload for ``tenant``.

    Parameters
    ----------
    tenant          : tenants.models.Tenant (ideally with unit__building prefetched)
    statement_date  : the "as at" date printed on the statement (default: today)
    as_of           : if given, only ledger rows on or before this date are included
                      (used when re-issuing a statement tied to a past payment)
    """
    statement_date = statement_date or _dt.date.today()
    unit = tenant.unit
    building = unit.building
    is_business = unit.classification == UnitClassification.BUSINESS

    rows, balance = _build_ledger(tenant, is_business=is_business, as_of=as_of)

    # "Current month" = the most recent rent obligation on/before the statement date.
    from .models import Arrears

    current_q = Arrears.objects.filter(
        tenant=tenant,
        period_year__lte=statement_date.year,
    )
    current = (
        current_q.filter(period_year__lt=statement_date.year)
        | current_q.filter(period_year=statement_date.year, period_month__lte=statement_date.month)
    ).order_by("-period_year", "-period_month").first()

    if current is not None:
        current_base = _money(current.expected_rent)
        current_period_label = _month_name(current.period_month, current.period_year)
    else:
        current_base = ZERO
        current_period_label = _month_name(statement_date.month, statement_date.year)

    vat_on_rent = (
        calculate_tax(current_base, UnitClassification.BUSINESS).tax_amount
        if is_business and current_base > 0 else ZERO
    )
    total_due = balance
    arrears_others = total_due - current_base - vat_on_rent

    paybill_number = building.paybill_number or ""
    paybill_account = building.paybill_account_for(unit.label) if paybill_number else ""

    return {
        # --- header ---
        "entity_name": building.legal_name or DEFAULT_ENTITY_NAME,
        "building_name": building.name,
        "building_address": building.address or "",
        "postal_address": building.postal_address or DEFAULT_POSTAL_ADDRESS,
        "contact_phone": building.contact_phone or DEFAULT_CONTACT_PHONE,
        "contact_email": building.contact_email or DEFAULT_CONTACT_EMAIL,
        "statement_date": _fmt_date(statement_date),

        # --- customer ---
        "tenant_name": tenant.full_name,
        "care_of": getattr(tenant, "care_of", "") or "",
        "kra_pin": tenant.kra_pin or "",
        "id_number": tenant.id_number or "",
        "tenant_phone": tenant.phone or "",
        "unit_label": unit.label,
        "unit_descriptor": _unit_descriptor(tenant),

        # --- summary ---
        "is_business": is_business,
        "arrears_others": _fmt_money(arrears_others),
        "current_month_rent": _fmt_money(current_base),
        "current_period_label": current_period_label,
        "vat_on_rent": _fmt_money(vat_on_rent),
        "total_due": _fmt_money(total_due),
        "total_due_whole": _fmt_money_whole(total_due),
        "total_due_value": total_due,
        "due_day_ordinal": _ordinal(tenant.due_day),

        # --- payment options ---
        "paybill_number": paybill_number,
        "paybill_account": paybill_account,
        "has_paybill": bool(paybill_number),
        "bank_name": building.bank_name or "",
        "bank_branch": building.bank_branch or "",
        "bank_account": building.bank_account or "",
        "bank_account_name": building.bank_account_name or "",
        "has_bank": bool(building.bank_account),

        # --- ledger ---
        "rows": rows,
    }
