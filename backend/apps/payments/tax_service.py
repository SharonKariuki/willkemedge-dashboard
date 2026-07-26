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


def split_tax_inclusive(
    gross_amount: Decimal,
    classification: str,
) -> TaxResult:
    """
    Decompose a VAT-INCLUSIVE gross receipt into net + tax.

    The mirror image of :func:`calculate_tax`. A commercial tenant pays rent and
    16% VAT as a single figure, so the *cash received* is VAT-inclusive and must
    be split apart — never grossed up again. A receipt of KES 27,840 is KES
    24,000 net income + KES 3,840 VAT. Residential rent is exempt: net == gross,
    tax == 0. This is the single source of truth used by both the Transaction/
    receipt (payments.services) and the ledger (ledger.posting), so the two can
    never diverge.

    Parameters
    ----------
    gross_amount    : cash actually received in KES (must be positive)
    classification  : UnitClassification value ("RESIDENTIAL" or "BUSINESS")

    Returns
    -------
    TaxResult where base_amount = net, tax_amount = VAT, total_amount = gross.
    net + tax == gross exactly (VAT absorbs the rounding).

    Raises
    ------
    ValueError if gross_amount <= 0 or classification is unrecognised.
    """
    if gross_amount <= 0:
        raise ValueError(f"gross_amount must be positive, got {gross_amount!r}")

    if classification == UnitClassification.BUSINESS:
        rate = TAX_RATE_BUSINESS
    elif classification == UnitClassification.RESIDENTIAL:
        rate = TAX_RATE_RESIDENTIAL
    else:
        raise ValueError(
            f"Unrecognised UnitClassification {classification!r}. "
            f"Expected one of: {[c.value for c in UnitClassification]}"
        )

    if rate == 0:
        return TaxResult(
            classification=classification,
            base_amount=gross_amount,
            tax_rate=rate,
            tax_amount=Decimal("0.00"),
            total_amount=gross_amount,
        )

    net = (gross_amount / (Decimal("1") + rate)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    tax_amount = gross_amount - net  # VAT absorbs the rounding so net + tax == gross
    return TaxResult(
        classification=classification,
        base_amount=net,
        tax_rate=rate,
        tax_amount=tax_amount,
        total_amount=gross_amount,
    )
