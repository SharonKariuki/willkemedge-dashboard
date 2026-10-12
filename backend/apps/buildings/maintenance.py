"""Keep a maintenance request's cost on the books.

A costed work order is an expense: it is booked to the unit under the COA's
"Repairs & Maintenance" category (GL 5200), and the ledger signal posts it.

This used to ``get_or_create`` a category called "Maintenance & Repairs" — the
COA's name the other way round. That created a category with no GL account,
and the ledger signal skips any expense whose category has none, so every
maintenance cost was on the Expenses page and missing from the books. The
category is now looked up, never created, and a missing one is an error.
"""
from rest_framework.exceptions import ValidationError

from apps.expenses.models import Expense, ExpenseCategory

#: The COA expense category a work order's cost is booked under
#: (see ``apps.expenses.coa.EXPENSE_CATEGORIES``).
MAINTENANCE_CATEGORY = "Repairs & Maintenance"


def maintenance_category() -> ExpenseCategory:
    """The GL-mapped category maintenance costs post to."""
    category = (
        ExpenseCategory.objects.filter(name=MAINTENANCE_CATEGORY, account__isnull=False)
        .select_related("account")
        .first()
    )
    if category is None:
        raise ValidationError({
            "cost": [
                f"The '{MAINTENANCE_CATEGORY}' expense category is missing or has no "
                f"GL account. Run `manage.py seed_coa` before recording a costed request."
            ]
        })
    return category


def sync_maintenance_expense(request) -> None:
    """Create, update or remove the expense behind a maintenance request.

    * a cost and no expense yet → book one (also when the cost is added later);
    * a changed cost → the expense follows, and the ledger re-posts it;
    * the cost taken off → the expense is deleted, which posts its reversal.
    """
    cost = request.cost or 0
    expense = request.expense

    if cost <= 0:
        if expense is not None:
            request.expense = None
            request.save(update_fields=["expense"])
            expense.delete()
        return

    if expense is None:
        request.expense = Expense.objects.create(
            date=request.reported_date,
            building=request.unit.building,
            # The work order is always for one unit, so the cost it
            # generates is booked to that unit, not just the building.
            unit=request.unit,
            category=maintenance_category(),
            amount=cost,
            description=f"Maintenance: {request.description[:200]}",
            reference=f"MNT-{request.pk}",
            period_month=request.reported_date.month,
            period_year=request.reported_date.year,
            notes=f"Auto-created from maintenance request #{request.pk}",
        )
        request.save(update_fields=["expense"])
        return

    if expense.amount != cost:
        expense.amount = cost
        expense.save(update_fields=["amount", "updated_at"])
