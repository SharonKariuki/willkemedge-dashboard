"""
How large a rent security deposit a letting should hold.

One rule, one place. It was previously spelled ``monthly_rent * 3`` inside
``check_data_integrity`` and again inside ``apply_matasia_answers``, and the
tenant API did not know about it at all — so the deposit card showed what was
held with nothing to hold it against, and a residential deposit could sit at
zero indefinitely without anything saying so.

The policy is one month's rent everywhere except the commercial arcade, which
takes three. Matasia Commercial is the only BUSINESS-classified building in the
portfolio, so classification is the distinction the code keys on rather than a
building code: that keeps a future commercial letting on the three-month rule
without anyone having to remember to add it here, and it is the same axis the
VAT and receipt-layout logic already turns on.

``deposit_paid`` records what was actually received and is never adjusted to
match this rule. Where the two differ the shortfall is a fact worth keeping,
not a number to round up to policy — MCG05 sat at 390,780 against an expected
259,500 for a month precisely because an odd figure went unquestioned.
"""
from decimal import Decimal

ZERO = Decimal("0.00")
CENTS = Decimal("0.01")

#: Months of rent a letting's security deposit should be, by classification.
RESIDENTIAL_MONTHS = 1
COMMERCIAL_MONTHS = 3


def deposit_months(tenant) -> int:
    """How many months' rent this letting's deposit should be.

    A tenancy with no unit falls to the residential rule; it has no
    classification to read and one month is the portfolio default.
    """
    from apps.buildings.models import UnitClassification

    unit = getattr(tenant, "unit", None)
    if unit is not None and unit.classification == UnitClassification.BUSINESS:
        return COMMERCIAL_MONTHS
    return RESIDENTIAL_MONTHS


def expected_deposit(tenant) -> Decimal:
    """The deposit this letting should hold under the rule."""
    rent = tenant.monthly_rent or ZERO
    return (Decimal(rent) * deposit_months(tenant)).quantize(CENTS)


def deposit_shortfall(tenant) -> Decimal:
    """How far short of the rule the held deposit falls, floored at zero.

    An excess is not a shortfall. It is still worth knowing about — that is what
    ``check_data_integrity`` reports — but it is not money owed to the landlord.
    """
    held = Decimal(tenant.deposit_paid or ZERO)
    return max(expected_deposit(tenant) - held, ZERO).quantize(CENTS)
