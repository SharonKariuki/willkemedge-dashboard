"""
Tax service — single source of truth for all tax logic.

Nothing in the payment system should hardcode VAT rates or classification
rules. Everything routes through here so future rate changes require
editing exactly one file.

Public API
----------
calculate_tax(base_amount, classification) -> TaxResult
TAX_RATE_BUSINESS   : Decimal  (informational constant)
TAX_RATE_RESIDENTIAL: Decimal  (informational constant)
"""
from decimal import ROUND_HALF_UP, Decimal
from typing import NamedTuple

from apps.buildings.models import UnitClassification

# ---------------------------------------------------------------------------
# Rate constants — change rates here and nowhere else.
# ---------------------------------------------------------------------------
TAX_RATE_BUSINESS: Decimal = Decimal("0.16")    # 16 % VAT
TAX_RATE_RESIDENTIAL: Decimal = Decimal("0.00") # exempt


class TaxResult(NamedTuple):
    """Immutable snapshot of a tax calculation.  All values stored at write time."""

    classification: str    # "RESIDENTIAL" | "BUSINESS"
    base_amount: Decimal
    tax_rate: Decimal      # e.g. 0.16
    tax_amount: Decimal    # base_amount * tax_rate, rounded to 2 dp
    total_amount: Decimal  # base_amount + tax_amount


def calculate_tax(
    base_amount: Decimal,
    classification: str,
) -> TaxResult:
    """
    Compute tax for a given base amount and unit classification.

    Parameters
    ----------
    base_amount     : gross rent in KES (must be positive)
    classification  : UnitClassification value ("RESIDENTIAL" or "BUSINESS")

    Returns
    -------
    TaxResult with all derived fields pre-computed and rounded to 2 dp.

    Raises
    ------
    ValueError if base_amount <= 0 or classification is unrecognised.
    """
    if base_amount <= 0:
        raise ValueError(f"base_amount must be positive, got {base_amount!r}")

    if classification == UnitClassification.BUSINESS:
        rate = TAX_RATE_BUSINESS
    elif classification == UnitClassification.RESIDENTIAL:
        rate = TAX_RATE_RESIDENTIAL
    else:
        raise ValueError(
            f"Unrecognised UnitClassification {classification!r}. "
            f"Expected one of: {[c.value for c in UnitClassification]}"
        )

    tax_amount = (base_amount * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total_amount = base_amount + tax_amount

    return TaxResult(
        classification=classification,
        base_amount=base_amount,
        tax_rate=rate,
        tax_amount=tax_amount,
        total_amount=total_amount,
    )
