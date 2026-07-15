"""
JSON-driven rent-statement generator.

Produces PDFs that reproduce the official Wilkem Edge rent statement
(templates/payments/statement_official.html) from plain tenant dicts — no
database rows required. The running balances, water charges, arrears, current
month, and total due are all computed here, not trusted from the input.

Public API
----------
generate_statement_pdf(data)               -> bytes         (the PDF)
generate_statement_file(data, out_dir)     -> Path          (writes "Unit <x>.pdf")
generate_statements(tenants, out_dir)      -> list[Path]    (loops)
build_context(data)                        -> dict          (template context; testable)

Input shape (see the module docstring example in the management command)::

    {
      "tenant_name": "John Doe", "unit": "4B",
      "pin": "A00...", "id_number": "123...", "phone": "0712...",
      "month": "June-2026", "statement_date": "4 June 2026",
      "opening_balance": 0,                       # optional, default 0
      "transactions": [
        {"date": "1 June 2026", "description": "Month Rent - June 2026",
         "invoice_amount": 20000, "payments": 0},
        {"date": "3 June 2026", "type": "water", "label": "Water usage - May '26",
         "opening_reading": 1456, "closing_reading": 1463, "rate": 150},
        {"date": "24 June 2026", "description": "Payment Received",
         "invoice_amount": 0, "payments": 20000}
      ]
    }
"""
from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

# Donholm defaults, matching the official template. Any can be overridden per
# statement via the input dict (or a nested "building" block).
DEFAULTS = {
    "entity_name": "WILKEM EDGE APARTMENTS",
    "entity_location": "DONHOLM ESTATE, NAIROBI",
    "postal_address": "BOX 66741 - 00800 NAIROBI",
    "contact_phone": "+254 722 527234 | +254 732 527234",
    "contact_email": "wilkem.ventures@gmail.com",
    "paybill_number": "400222",
    "paybill_account_format": "90290#{unit}",
    "bank_account": "01136069098300",
    "bank_branch": "Karen Branch",
    "due_day_ordinal": "5th",
    "water_rate": 150,
}


def _dec(value) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    return Decimal(str(value))


def _whole(value) -> str:
    """'23,350' for whole values, '23,350.50' otherwise. Blank-safe negatives."""
    amt = _dec(value)
    if amt == amt.to_integral_value():
        return f"{int(amt):,}"
    return f"{amt:,.2f}"


def _money(value) -> str:
    """'20,000.00' — always 2 dp (used in the summary box)."""
    return f"{_dec(value):,.2f}"


def _cell(value) -> str:
    """A ledger money cell: shown when non-zero, blank when zero (like the template)."""
    return _whole(value) if _dec(value) != 0 else ""


def _int_if_whole(value):
    amt = _dec(value)
    return int(amt) if amt == amt.to_integral_value() else amt


def _row_description(txn: dict) -> tuple[list[str], Decimal, Decimal]:
    """Return (description_lines, invoice_amount, payments) for one transaction.

    A water transaction (``type: "water"`` or opening/closing readings present)
    has its consumption and charge computed here and rendered as the multi-line
    '<label> (N units) / Opening Reading / Closing Reading' block.
    """
    is_water = txn.get("type") == "water" or (
        txn.get("opening_reading") is not None and txn.get("closing_reading") is not None
    )
    if is_water:
        opening = _dec(txn.get("opening_reading"))
        closing = _dec(txn.get("closing_reading"))
        rate = _dec(txn.get("rate", DEFAULTS["water_rate"]))
        units = closing - opening
        invoice = (units * rate) if txn.get("amount") in (None, "") else _dec(txn.get("amount"))
        label = txn.get("label") or txn.get("description") or "Water usage"
        lines = [f"{label} ({_int_if_whole(units)} units)"]
        if txn.get("opening_reading") is not None:
            lines.append(f"Opening Reading: {_int_if_whole(opening)}")
        if txn.get("closing_reading") is not None:
            lines.append(f"Closing Reading: {_int_if_whole(closing)}")
        return lines, invoice, _dec(txn.get("payments"))

    desc = str(txn.get("description", ""))
    return desc.split("\n"), _dec(txn.get("invoice_amount")), _dec(txn.get("payments"))


def build_context(data: dict) -> dict:
    """Turn a tenant dict into the template context, computing every derived value."""
    unit = str(data.get("unit", "")).strip()

    # Resolve building/branding fields (input overrides defaults).
    src = {**DEFAULTS, **(data.get("building") or {}), **data}
    paybill_account = str(src.get("paybill_account")
                          or DEFAULTS["paybill_account_format"].format(unit=unit))

    rows = []
    balance = _dec(data.get("opening_balance"))
    last_rent = Decimal("0")
    start = int(data.get("start_index", 1))

    for i, txn in enumerate(data.get("transactions", []), start=start):
        lines, invoice, payments = _row_description(txn)
        balance += invoice - payments
        if invoice > 0 and re.search(r"\brent\b", lines[0], re.IGNORECASE):
            last_rent = invoice  # current-month rent = the most recent rent charge
        rows.append({
            "index": txn.get("no", i),
            "date": txn.get("date", ""),
            "description_lines": lines,
            "invoice_amount": _cell(invoice),
            "payments": _cell(payments),
            "balance": _whole(balance),
            "balance_negative": balance < 0,
        })

    total_due = balance
    current_month = _dec(data.get("current_month_rent")) if data.get("current_month_rent") is not None else last_rent
    arrears_others = total_due - current_month

    return {
        "tenant_name": data.get("tenant_name", ""),
        "pin": data.get("pin", ""),
        "id_number": data.get("id_number", ""),
        "phone": data.get("phone", ""),
        "unit": unit,
        "unit_descriptor": data.get("unit_descriptor") or (f"Unit {unit}" if unit else ""),
        "statement_date": data.get("statement_date", ""),
        "billing_month": data.get("month", ""),

        "entity_name": src["entity_name"],
        "entity_location": src["entity_location"],
        "postal_address": src["postal_address"],
        "contact_phone": src["contact_phone"],
        "contact_email": src["contact_email"],
        "paybill_number": src["paybill_number"],
        "paybill_account": paybill_account,
        "bank_account": src["bank_account"],
        "bank_branch": src["bank_branch"],
        "due_day_ordinal": src["due_day_ordinal"],

        "arrears_others": _money(arrears_others),
        "current_month": _money(current_month),
        "total_due": _money(total_due),
        "total_due_whole": _whole(total_due),

        "rows": rows,
    }


def generate_statement_pdf(data: dict) -> bytes:
    """Render one tenant's statement to PDF bytes."""
    from .pdf_service import render_to_pdf

    pdf = render_to_pdf("payments/statement_official.html", build_context(data))
    if pdf is None:
        raise RuntimeError(f"PDF render failed for unit {data.get('unit')!r}")
    return pdf


def _safe_filename(unit: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(unit or "statement").strip())
    return f"Unit {cleaned}.pdf"


def generate_statement_file(data: dict, out_dir) -> Path:
    """Write one tenant's statement to '<out_dir>/Unit <unit>.pdf'."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / _safe_filename(data.get("unit"))
    path.write_bytes(generate_statement_pdf(data))
    return path


def generate_statements(tenants: list[dict], out_dir) -> list[Path]:
    """Loop: one PDF per tenant. Returns the written file paths."""
    return [generate_statement_file(t, out_dir) for t in tenants]
