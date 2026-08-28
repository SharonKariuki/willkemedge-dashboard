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

from django.db.models import Q, Sum

from apps.buildings.models import UnitClassification
from apps.expenses.coa import (
    DEPOSITS_HELD,
    RENT_COMMERCIAL,
    RENT_RECEIVABLE,
    RENT_RESIDENTIAL,
    SERVICE_CHARGE_UTILITIES,
)

from .monthly_ledger import OPENING_MARKER

ZERO = Decimal("0.00")

# Project-wide fallbacks used when a Building has no per-building override.
DEFAULT_ENTITY_NAME = "Wilkem Edge Apartments"
DEFAULT_POSTAL_ADDRESS = "PO Box 66741 - 00800, Nairobi, Kenya"
DEFAULT_CONTACT_PHONE = "+254 722 527234 / +254 732 527234"
DEFAULT_CONTACT_EMAIL = "wilkem.ventures@gmail.com"

# Payment-option fallbacks (Wilkem Ventures production details). Used so the
# statement always shows real payment instructions instead of the
# "contact the management office" placeholder when a Building hasn't had its
# bank/paybill fields filled in yet.
DEFAULT_BANK_NAME = "Cooperative Bank"
DEFAULT_BANK_BRANCH = "Karen Branch"
DEFAULT_BANK_ACCOUNT = "01136069098300"
DEFAULT_BANK_ACCOUNT_NAME = "Wilkem Ventures Company Ltd"
DEFAULT_PAYBILL_NUMBER = "400222"




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
    from .models import Arrears, Payment, PaymentType, UtilityCharge

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
        period = _month_name(arr.period_month, arr.period_year)

        # A carried opening balance is stored as an Arrears row because that is
        # the only way to seed the roll-forward, but it is not a month's rent —
        # printing it as "Month Rent" put 20,000 against Elimisha's July when
        # their rent is 22,500. It attracts no VAT either: whatever tax was due
        # is already inside the figure carried.
        if OPENING_MARKER in (arr.waive_notes or ""):
            events.append((posting, 0, f"Balance brought forward - {period}", base, ZERO))
        else:
            # VAT is read from the row, not recomputed. Not every commercial
            # letting is rated — MCG02 is billed with none — and deriving 16%
            # here charged tax on the statement that the ledger never raised.
            vat = _money(arr.expected_vat)
            events.append((posting, 0, f"Month Rent - {period}", base, ZERO))
            if vat > 0:
                events.append((posting, 1, "16% VAT on Rent", vat, ZERO))

        # A waiver discharges the obligation just as cash does. Without this
        # credit the statement kept showing debt the business had already
        # written off — permanently, since the charge row is never removed.
        waived = _money(arr.waived_amount)
        if waived > 0:
            label = f"Waiver - {_month_name(arr.period_month, arr.period_year)}"
            if arr.waive_notes:
                label = f"{label} ({arr.waive_notes})"
            events.append((posting, 4, label, ZERO, waived))

    for util in UtilityCharge.objects.filter(tenant=tenant).order_by("posting_date", "id"):
        if as_of and util.posting_date > as_of:
            continue
        events.append((util.posting_date, 2, util.description(), _money(util.amount), ZERO))

    # Deposits are excluded: a security deposit is a refundable liability, not a
    # payment against rent. Crediting it here reduced the rent owed *and* showed
    # the same money again on the "Security Deposit" breakdown line. Voided
    # payments are excluded because the money was never really received.
    payments = (
        Payment.objects.filter(tenant=tenant, voided_at__isnull=True)
        .exclude(payment_type=PaymentType.DEPOSIT)
        .order_by("payment_date", "created_at")
    )
    for pay in payments:
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

    # Due date: the tenant's due-day in the month following the statement,
    # e.g. a statement dated 26 Jul 2026 is due "5th August 2026".
    import calendar
    _dy, _dm = (statement_date.year + 1, 1) if statement_date.month == 12 else (statement_date.year, statement_date.month + 1)
    _dday = min(int(tenant.due_day), calendar.monthrange(_dy, _dm)[1])
    due_date = f"{_ordinal(_dday)} {_dt.date(_dy, _dm, _dday).strftime('%B %Y')}"

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

    # Read the VAT actually raised rather than deriving it, for the same reason
    # the ledger rows do: a commercial unit is not necessarily VAT-rated.
    vat_on_rent = _money(current.expected_vat) if current is not None else ZERO
    total_due = balance
    arrears_others = total_due - current_base - vat_on_rent

    # --- Receipt breakdown (Feature 7) ---------------------------------------
    # Five named figures for the SMS/email receipt, each sourced from real
    # records. These are informational: the authoritative amount owed remains
    # `total_due` ("Unpaid Balance"). They are additive to the account rather
    # than a re-derivation of the net balance.
    from .models import Payment, PaymentType, UtilityCharge

    #  Security deposit held = deposit-type payments received (up to as_of).
    deposit_q = Payment.objects.filter(
        tenant=tenant, payment_type=PaymentType.DEPOSIT, voided_at__isnull=True
    )
    if as_of:
        deposit_q = deposit_q.filter(payment_date__lte=as_of)
    security_deposit = _money(deposit_q.aggregate(t=Sum("amount"))["t"])

    #  Arrears brought forward = rent balance for periods before the current one.
    bf_q = Arrears.objects.filter(tenant=tenant)
    if current is not None:
        bf_q = bf_q.filter(
            Q(period_year__lt=current.period_year)
            | Q(period_year=current.period_year, period_month__lt=current.period_month)
        )
    arrears_bf = _money(bf_q.aggregate(t=Sum("balance"))["t"])

    #  Other charges = non-rent utility charges posted (up to as_of).
    util_q = UtilityCharge.objects.filter(tenant=tenant)
    if as_of:
        util_q = util_q.filter(posting_date__lte=as_of)
    other_charges = _money(util_q.aggregate(t=Sum("amount"))["t"])

    #  Rent income code depends on the unit's tax classification.
    rent_code = RENT_COMMERCIAL if is_business else RENT_RESIDENTIAL
    rent_name = "Commercial Rental Income" if is_business else "Residential Rental Income"

    # Payment options: prefer per-building values, fall back to the Wilkem
    # Ventures defaults so the statement never shows the placeholder text.
    paybill_number = building.paybill_number or DEFAULT_PAYBILL_NUMBER
    paybill_account = (
        building.paybill_account_for(unit.label) if building.paybill_number else ""
    )
    bank_name = building.bank_name or DEFAULT_BANK_NAME
    bank_branch = building.bank_branch or DEFAULT_BANK_BRANCH
    bank_account = building.bank_account or DEFAULT_BANK_ACCOUNT
    bank_account_name = building.bank_account_name or DEFAULT_BANK_ACCOUNT_NAME

    return {
        # --- header ---
        "entity_name": building.legal_name or DEFAULT_ENTITY_NAME,
        "building_name": building.name,
        "building_address": building.address or "",
        "postal_address": building.postal_address or DEFAULT_POSTAL_ADDRESS,
        "contact_phone": building.contact_phone or DEFAULT_CONTACT_PHONE,
        "contact_email": building.contact_email or DEFAULT_CONTACT_EMAIL,
        "statement_date": _fmt_date(statement_date),
        "due_date": due_date,

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

        # --- receipt breakdown: the named totals ---
        "security_deposit": _fmt_money(security_deposit),
        "arrears_bf": _fmt_money(arrears_bf),
        "month_rent": _fmt_money(current_base),
        "other_charges": _fmt_money(other_charges),
        "rent_plus_arrears": _fmt_money(current_base + arrears_bf),
        "unpaid_balance": _fmt_money(total_due),

        # Each receipt line itemised with the GL code it posts to, so the
        # statement reconciles directly against the Chart of Accounts.
        # (label, amount, coa_code, coa_name)
        "breakdown_lines": [
            ("Security Deposit", _fmt_money(security_deposit), DEPOSITS_HELD, "Tenant Security Deposits Held"),
            ("Arrears Brought Forward", _fmt_money(arrears_bf), RENT_RECEIVABLE, "Accounts Receivable (Rent Arrears)"),
            ("Month Rent", _fmt_money(current_base), rent_code, rent_name),
            ("Other Charges", _fmt_money(other_charges), SERVICE_CHARGE_UTILITIES, "Service Charge / Utilities"),
            ("Rent + Arrears", _fmt_money(current_base + arrears_bf), RENT_RECEIVABLE, "Accounts Receivable (Rent Arrears)"),
            ("Unpaid Balance", _fmt_money(total_due), RENT_RECEIVABLE, "Accounts Receivable (Rent Arrears)"),
        ],

        # --- payment options ---
        "paybill_number": paybill_number,
        "paybill_account": paybill_account,
        "has_paybill": bool(paybill_number),
        "bank_name": bank_name,
        "bank_branch": bank_branch,
        "bank_account": bank_account,
        "bank_account_name": bank_account_name,
        "has_bank": bool(bank_account),

        # --- ledger ---
        "rows": rows,
    }
