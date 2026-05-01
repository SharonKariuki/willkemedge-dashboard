"""
Receipt service — generates receipt data from stored Transaction records.

Design rules
------------
- Pulls exclusively from stored Transaction fields; never recalculates derived values.
- Returns a plain dict (ReceiptData) so it can be consumed by any renderer:
  PDF generator, SMS template, JSON API, or React component.
- Conditional fields (VAT line, outstanding balance, etc.) are controlled by
  flags on the returned dict — not by caller logic — so rendering stays dumb.

Public API
----------
generate_receipt(transaction)  -> ReceiptData
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from apps.buildings.models import UnitClassification


@dataclass(frozen=True)
class ReceiptData:
    """
    Immutable receipt snapshot.  All values come from stored Transaction fields.

    show_tax_line       : True when unitType == BUSINESS (render VAT row)
    show_total_only     : True when unitType == RESIDENTIAL (hide tax, show total)
    outstanding_balance : Optional — pass from arrears if caller has it
    """

    # --- Core identifiers ---
    transaction_id: str
    reference_code: str
    payment_mode: str               # "MPESA" | "BANK" | "CASH" | "CHEQUE"

    # --- Party info ---
    tenant_name: str
    unit_label: str
    building_name: str
    period_month: int
    period_year: int

    # --- Financial (stored values — never recalculated) ---
    unit_classification: str        # "RESIDENTIAL" | "BUSINESS"
    base_amount: Decimal
    tax_amount: Decimal
    total_amount: Decimal

    # --- Conditional rendering flags ---
    show_tax_line: bool             # True iff BUSINESS
    show_total_only: bool           # True iff RESIDENTIAL

    # --- Optional fields (toggled by caller) ---
    outstanding_balance: Optional[Decimal] = field(default=None)
    payment_date: Optional[str] = field(default=None)


def generate_receipt(
    transaction,
    *,
    outstanding_balance: Optional[Decimal] = None,
) -> ReceiptData:
    """
    Build a ReceiptData from a Transaction ORM instance.

    Parameters
    ----------
    transaction         : payments.models.Transaction (must have select_related
                          tenant__unit__building and payment pre-fetched)
    outstanding_balance : pass the tenant's current arrears balance if you want
                          that line rendered on the receipt.

    Returns
    -------
    ReceiptData — immutable, renderer-agnostic receipt snapshot.
    """
    tenant = transaction.tenant
    unit = tenant.unit
    payment = transaction.payment

    is_business = transaction.unit_classification == UnitClassification.BUSINESS

    return ReceiptData(
        transaction_id=transaction.transaction_id,
        reference_code=transaction.reference_code,
        payment_mode=transaction.payment_mode,

        tenant_name=tenant.full_name,
        unit_label=unit.label,
        building_name=unit.building.name,
        period_month=payment.period_month,
        period_year=payment.period_year,

        unit_classification=transaction.unit_classification,
        base_amount=transaction.base_amount,
        tax_amount=transaction.tax_amount,
        total_amount=transaction.total_amount,

        show_tax_line=is_business,
        show_total_only=not is_business,

        outstanding_balance=outstanding_balance,
        payment_date=str(payment.payment_date) if payment.payment_date else None,
    )
