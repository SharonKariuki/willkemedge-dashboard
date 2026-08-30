"""Age a tenant's outstanding balance into 0-30 / 31-60 / 61-90 / 90+ buckets.

The buckets are cut from the same figures as the rent roll — ``Arrears`` for
the monthly charge, ``UtilityCharge`` for other costs, ``Payment`` for cash —
so they always sum to the balance ``monthly_ledger.current_balance`` reports.
An aging table that does not add up to the balance printed beside it is worse
than no aging table at all, so that identity is the point of this module and
is asserted in the tests.

Cash is applied oldest-charge-first. That is what aging means: the question a
bucket answers is "how long has this money been owed", and a receipt settles
the oldest debt before it touches a newer one, whatever period the payer wrote
on it. A tenant whose cash covers everything owes nothing and is left out
entirely rather than appearing with empty buckets.

A charge is aged from the END of the month it belongs to, which is the date it
fell due — August rent is not overdue on 1 August.
"""
from __future__ import annotations

import calendar
import datetime as _dt
from decimal import Decimal

ZERO = Decimal("0.00")

BUCKETS = ("bucket_0_30", "bucket_31_60", "bucket_61_90", "bucket_90_plus")


def _money(value) -> Decimal:
    return (Decimal(value) if value is not None else ZERO).quantize(Decimal("0.01"))


def _period_end(year: int, month: int) -> _dt.date:
    return _dt.date(year, month, calendar.monthrange(year, month)[1])


def _bucket_for(days: int) -> str:
    if days <= 30:
        return "bucket_0_30"
    if days <= 60:
        return "bucket_31_60"
    if days <= 90:
        return "bucket_61_90"
    return "bucket_90_plus"


def aging_buckets(tenants, *, today: _dt.date | None = None) -> dict[int, dict]:
    """Return ``{tenant_id: {buckets…, "total", "oldest_period"}}``.

    Only tenants actually in debit appear. Three queries regardless of how many
    tenants are passed.
    """
    from django.db.models import Q

    from .models import Arrears, Payment, PaymentType, UtilityCharge
    from .monthly_ledger import OPENING_MARKER

    ids = [t.pk if hasattr(t, "pk") else int(t) for t in tenants]
    if not ids:
        return {}

    today = today or _dt.date.today()
    upto = Q(period_year__lt=today.year) | Q(
        period_year=today.year, period_month__lte=today.month
    )
    first_of_next_month = (today.replace(day=1) + _dt.timedelta(days=32)).replace(day=1)

    # charges[tenant_id] -> {(year, month): amount}
    charges: dict[int, dict[tuple[int, int], Decimal]] = {tid: {} for tid in ids}

    def _add(tenant_id, year, month, amount):
        if amount == ZERO:
            return
        bucket = charges[tenant_id]
        key = (year, month)
        bucket[key] = bucket.get(key, ZERO) + amount

    for arr in Arrears.objects.filter(tenant_id__in=ids).filter(upto):
        charge = (
            _money(arr.expected_rent)
            + _money(arr.expected_vat)
            - _money(arr.waived_amount)
        )
        _add(arr.tenant_id, arr.period_year, arr.period_month, charge)

    for util in UtilityCharge.objects.filter(tenant_id__in=ids).filter(upto):
        _add(util.tenant_id, util.period_year, util.period_month, _money(util.amount))

    received: dict[int, Decimal] = {tid: ZERO for tid in ids}
    payments = (
        Payment.objects.filter(
            tenant_id__in=ids,
            voided_at__isnull=True,
            payment_date__lt=first_of_next_month,
        )
        .exclude(payment_type=PaymentType.DEPOSIT)
        .values_list("tenant_id", "amount")
    )
    for tenant_id, amount in payments:
        received[tenant_id] += _money(amount)

    # An opening row is a balance carried from before the books began. Aging it
    # from its own month would call the whole pre-cutover history 30 days old,
    # so it keeps the age of the oldest month on file instead.
    opening_periods = {
        (row["tenant_id"], row["period_year"], row["period_month"])
        for row in Arrears.objects.filter(tenant_id__in=ids)
        .filter(upto)
        .filter(waive_notes__contains=OPENING_MARKER)
        .values("tenant_id", "period_year", "period_month")
    }

    result: dict[int, dict] = {}
    for tenant_id in ids:
        outstanding = sorted(charges[tenant_id].items())
        cash = received[tenant_id]
        buckets = dict.fromkeys(BUCKETS, ZERO)
        total = ZERO
        oldest: tuple[int, int] | None = None

        for (year, month), amount in outstanding:
            if cash >= amount:
                cash -= amount
                continue
            unpaid = amount - cash
            cash = ZERO
            is_opening = (tenant_id, year, month) in opening_periods
            days = (today - _period_end(year, month)).days
            key = "bucket_90_plus" if is_opening else _bucket_for(days)
            buckets[key] += unpaid
            total += unpaid
            if oldest is None:
                oldest = (year, month)

        if total <= ZERO:
            continue
        result[tenant_id] = {
            **{name: _money(value) for name, value in buckets.items()},
            "total": _money(total),
            "oldest_period": f"{oldest[1]}/{oldest[0]}" if oldest else "",
        }
    return result
