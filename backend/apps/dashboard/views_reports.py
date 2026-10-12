"""Dashboard views_reports — all reporting endpoints.

Every report reads live rows on each request; nothing is cached or
pre-computed, so a payment recorded a second ago is in the next response.

Filters every list report understands:
    building=<id>     one property
    status=current|former|all
                      current = active or on notice, former = moved out/archived
Period reports also take ``month`` and ``year``. A malformed parameter answers
400 with the reason (see ``report_data.int_param``).
"""
from collections import defaultdict
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.buildings.models import (
    OCCUPIED_UNIT_STATUSES,
    Building,
    UnitStatus,
)
from apps.payments.aging import BUCKETS, aging_buckets
from apps.payments.models import Arrears, Payment, PaymentType
from apps.payments.monthly_ledger import build_monthly_ledger, current_balances
from apps.tenants.models import Tenant, TenantStatus

from .report_data import (
    INCOME_PAYMENT_FILTER,
    ZERO,
    building_param,
    expense_by_category,
    income_lines,
    income_total,
    int_param,
    money,
    month_end,
    month_start,
    period_params,
)

# Kept under their old names: the dashboard summary imports them from here.
__all__ = ["INCOME_PAYMENT_FILTER"]

CURRENT_STATUSES = (TenantStatus.ACTIVE, TenantStatus.NOTICE_GIVEN)


def _today():
    return timezone.localdate()


def _f(value) -> float:
    return float(money(value))


def _unit_name(unit) -> str:
    return f"{unit.building.name} — {unit.space_label}"


def _tenant_qs(request):
    """Tenants narrowed by ``building`` and ``status``."""
    qs = Tenant.objects.select_related("unit", "unit__building").prefetch_related(
        "unit__combined_units"
    )
    building_id = building_param(request)
    if building_id:
        qs = qs.filter(unit__building_id=building_id)
    status = request.query_params.get("status", "all")
    if status == "current":
        qs = qs.filter(status__in=CURRENT_STATUSES)
    elif status == "former":
        qs = qs.exclude(status__in=CURRENT_STATUSES)
    elif status != "all":
        raise ValidationError({"status": "Use current, former or all."})
    return qs


def _date_param(request, name):
    raw = request.query_params.get(name)
    if not raw:
        return None
    value = parse_date(raw)
    if value is None:
        raise ValidationError({name: f"'{raw}' is not a date (YYYY-MM-DD)."})
    return value


def _period_range(request):
    """Optional ``from``/``to`` as ``YYYY-MM`` → comparable month keys."""
    keys = []
    for name in ("from", "to"):
        raw = request.query_params.get(name)
        if not raw:
            keys.append(None)
            continue
        try:
            year, month = (int(part) for part in raw.split("-")[:2])
            if not 1 <= month <= 12:
                raise ValueError
        except ValueError:
            raise ValidationError({name: f"'{raw}' is not a month (YYYY-MM)."}) from None
        keys.append(year * 12 + month - 1)
    return keys


def _building_meta(building_id):
    if not building_id:
        return None
    building = Building.objects.filter(pk=building_id).only("id", "name").first()
    if building is None:
        raise ValidationError({"building": "No such building."})
    return {"id": building.id, "name": building.name}


class MonthlyCollectionReportView(APIView):
    """GET /api/reports/monthly-collection/?month=&year=&building=&type=

    Cash received in the month — by the date it arrived, the way the bank
    statement and the landlord's spreadsheet list it — whatever period it was
    allocated to. Deposits are held, not collected income, and are totalled
    separately; voided payments never arrived.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        today = _today()
        month, year = period_params(request, today)
        building_id = building_param(request)
        payment_type = request.query_params.get("type") or None
        if payment_type and payment_type not in PaymentType.values:
            raise ValidationError({"type": f"Use one of {', '.join(PaymentType.values)}."})

        base = Payment.objects.filter(
            voided_at__isnull=True,
            payment_date__gte=month_start(year, month),
            payment_date__lte=month_end(year, month),
        )
        if building_id:
            base = base.filter(tenant__unit__building_id=building_id)

        deposits = money(
            base.filter(payment_type=PaymentType.DEPOSIT).aggregate(t=Sum("amount"))["t"]
        )
        payments = base.exclude(payment_type=PaymentType.DEPOSIT)
        if payment_type:
            payments = base.filter(payment_type=payment_type)
        payments = payments.select_related(
            "tenant", "tenant__unit", "tenant__unit__building"
        ).prefetch_related("tenant__unit__combined_units").order_by(
            "payment_date", "tenant__unit__building__name", "tenant__unit__label", "id"
        )

        rows = []
        by_source = defaultdict(lambda: ZERO)
        total = ZERO
        for p in payments:
            amount = money(p.amount)
            total += amount
            by_source[p.get_source_display()] += amount
            rows.append({
                "id": p.id,
                "tenant_id": p.tenant_id,
                "tenant": p.tenant.full_name,
                "unit": _unit_name(p.tenant.unit),
                "amount": float(amount),
                "type": p.get_payment_type_display(),
                "period": f"{p.period_month}/{p.period_year}",
                "source": p.get_source_display(),
                "date": p.payment_date.isoformat(),
                "reference": p.reference,
            })

        return Response({
            "period": f"{month}/{year}",
            "building": _building_meta(building_id),
            "total": float(total),
            "count": len(rows),
            "deposits_received": float(deposits),
            "by_source": [
                {"source": source, "total": float(amount)}
                for source, amount in sorted(by_source.items(), key=lambda kv: -kv[1])
            ],
            "payments": rows,
        })


class AnnualIncomeSummaryView(APIView):
    """GET /api/reports/annual-income/?year=&building=

    Same figures, month for month, as the P&L's annual view: rent net of VAT,
    late fees, other income, farm and other manual income, credits.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        year = int_param(request, "year", _today().year, lo=2000, hi=2100)
        building_id = building_param(request)
        monthly = []
        grand_total = ZERO
        for m in range(1, 13):
            lines = income_lines(m, year, building_id=building_id)
            manual = sum((amount for _, amount in lines["manual_income"]), ZERO)
            monthly.append({
                "month": m,
                "total": float(lines["total"]),
                "rent": float(lines["residential_rent"] + lines["commercial_rent"]),
                "other": float(
                    lines["late_fees"] + lines["other_income"] + lines["credit_adjustment"]
                ),
                "manual": float(manual),
            })
            grand_total += lines["total"]
        return Response({
            "year": year,
            "building": _building_meta(building_id),
            "grand_total": float(grand_total),
            "monthly": monthly,
        })


class ArrearsReportView(APIView):
    """GET /api/reports/arrears/?building=&status= — who owes, one row per tenant.

    The balance is the rent-roll balance the tenant's own statement closes on —
    water and other charges included, cash in credit recognised.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        tenants = list(_tenant_qs(request))
        balances = current_balances(tenants, today=_today())

        # The oldest period still open is what "since" means on the report.
        oldest_open = {}
        for a in Arrears.objects.filter(
            tenant_id__in=[t.id for t in tenants], is_cleared=False
        ).order_by("tenant_id", "period_year", "period_month"):
            oldest_open.setdefault(a.tenant_id, a)

        charged_paid = _charged_and_paid(tenants)

        rows = []
        for tenant in tenants:
            balance = balances.get(tenant.id, ZERO)
            if balance <= 0:
                continue  # square, or in credit — not an arrear
            period = oldest_open.get(tenant.id)
            rent, vat, other, paid = charged_paid.get(tenant.id, (ZERO, ZERO, ZERO, ZERO))
            rows.append({
                "tenant_id": tenant.id,
                "tenant": tenant.full_name,
                "unit": _unit_name(tenant.unit),
                "status": tenant.get_status_display(),
                "phone": tenant.phone,
                "period": (
                    f"{period.period_month}/{period.period_year}" if period else "—"
                ),
                # Rent + VAT, split out so a commercial row's obligation checks
                # out on screen the same way the payment-history endpoint shows it.
                "expected": float(rent + vat + other),
                "expected_rent": float(rent),
                "expected_vat": float(vat),
                "paid": float(paid),
                "balance": float(balance),
            })

        rows.sort(key=lambda r: -r["balance"])
        return Response({
            "building": _building_meta(building_param(request)),
            "total_balance": float(sum((Decimal(str(r["balance"])) for r in rows), ZERO)),
            "count": len(rows),
            "arrears": rows,
        })


def _charged_and_paid(tenants):
    """``{tenant_id: (rent, vat, other, paid)}`` — the figures behind the balance.

    Everything up to and including the current month, the same window the
    balance is struck over, so rent + vat + other − paid is the balance with
    no unexplained figure. ``other`` folds in waivers and credits (negative),
    utility charges and refunds (positive).
    """
    import datetime as _dt

    from apps.payments.credits import issued_credits, sent_refunds
    from apps.payments.models import UtilityCharge
    from apps.payments.monthly_ledger import upto_current_period

    today = _today()
    upto = upto_current_period(today)
    next_month = (today.replace(day=1) + _dt.timedelta(days=32)).replace(day=1)

    ids = [t.pk for t in tenants]
    totals = {tid: [ZERO, ZERO, ZERO, ZERO] for tid in ids}

    for row in (
        Arrears.objects.filter(tenant_id__in=ids).filter(upto)
        .values("tenant_id")
        .annotate(rent=Sum("expected_rent"), vat=Sum("expected_vat"), waived=Sum("waived_amount"))
    ):
        totals[row["tenant_id"]][0] += money(row["rent"])
        totals[row["tenant_id"]][1] += money(row["vat"])
        totals[row["tenant_id"]][2] -= money(row["waived"])

    for row in (
        UtilityCharge.objects.filter(tenant_id__in=ids).filter(upto)
        .values("tenant_id").annotate(total=Sum("amount"))
    ):
        totals[row["tenant_id"]][2] += money(row["total"])

    for row in (
        Payment.objects.filter(tenant_id__in=ids, payment_date__lt=next_month)
        .filter(INCOME_PAYMENT_FILTER)
        .values("tenant_id").annotate(total=Sum("amount"))
    ):
        totals[row["tenant_id"]][3] += money(row["total"])

    # Credits given reduce what was charged; refunds paid back out add to it.
    for row in (
        issued_credits(ids).filter(credit_date__lt=next_month)
        .values("tenant_id").annotate(total=Sum("amount"))
    ):
        totals[row["tenant_id"]][2] -= money(row["total"])
    for row in (
        sent_refunds(ids).filter(sent_on__lt=next_month)
        .values("tenant_id").annotate(total=Sum("amount"))
    ):
        totals[row["tenant_id"]][2] += money(row["total"])

    return {tid: tuple(values) for tid, values in totals.items()}


class AgingArrearsReportView(APIView):
    """GET /api/reports/aging-arrears/?building=&status= — balances by age.

    Buckets are cut from the rent roll and sum to the balance the rest of the
    product reports.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        tenants = list(_tenant_qs(request))
        buckets = aging_buckets(tenants, today=_today())

        rows = []
        for tenant in tenants:
            aged = buckets.get(tenant.id)
            if not aged:
                continue
            rows.append({
                "tenant_id": tenant.id,
                "tenant": tenant.full_name,
                "unit": _unit_name(tenant.unit),
                "status": tenant.get_status_display(),
                "oldest_period": aged["oldest_period"],
                **{name: float(aged[name]) for name in BUCKETS},
                "total": float(aged["total"]),
            })

        rows.sort(key=lambda r: -r["total"])
        listed = {r["tenant_id"] for r in rows}
        totals = {
            name: float(sum((buckets[tid][name] for tid in listed), ZERO)) for name in BUCKETS
        }
        return Response({
            "building": _building_meta(building_param(request)),
            "grand_total": float(sum((buckets[tid]["total"] for tid in listed), ZERO)),
            "bucket_totals": totals,
            "count": len(rows),
            "aging": rows,
        })


class TenantPaymentHistoryView(APIView):
    """GET /api/reports/tenant-history/<tenant_id>/?months=12

    Charged vs paid, month by month, straight off the tenant's rent roll —
    VAT and water included in what was charged, cash in the month it arrived.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, tenant_id):
        tenant = get_object_or_404(
            Tenant.objects.select_related("unit", "unit__building"), pk=tenant_id
        )
        months = int_param(request, "months", 12, lo=0, hi=240)
        ledger = build_monthly_ledger(tenant, months=months, today=_today())

        chart_data = []
        for row in ledger:
            charged = (
                Decimal(row["rent"]) + Decimal(row["vat"])
                + Decimal(row["other_charges"]) + Decimal(row["refunds"])
            )
            chart_data.append({
                "month": f"{row['period_year']}-{row['period_month']:02d}",
                "label": row["label"],
                "paid": float(row["paid"]),
                "expected": float(charged),
                "balance": float(row["balance"]),
            })

        total_paid = money(
            Payment.objects.filter(INCOME_PAYMENT_FILTER, tenant=tenant)
            .aggregate(t=Sum("amount"))["t"]
        )
        return Response({
            "tenant": {
                "id": tenant.id,
                "name": tenant.full_name,
                "unit": _unit_name(tenant.unit),
                "monthly_rent": float(tenant.monthly_rent),
                "status": tenant.get_status_display(),
            },
            "chart_data": chart_data,
            "total_paid": float(total_paid),
            "period_paid": float(sum((Decimal(str(r["paid"])) for r in chart_data), ZERO)),
            "balance": float(current_balances([tenant], today=_today()).get(tenant.id, ZERO)),
        })


class OccupancyHistoryView(APIView):
    """GET /api/reports/occupancy/?building="""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        building_id = building_param(request)
        qs = Building.objects.annotate(
            total=Count("units"),
            occ=Count("units", filter=Q(units__status__in=OCCUPIED_UNIT_STATUSES)),
            vacant=Count("units", filter=Q(units__status=UnitStatus.VACANT)),
            maintenance=Count("units", filter=Q(units__status=UnitStatus.UNDER_MAINTENANCE)),
        ).order_by("name")
        if building_id:
            qs = qs.filter(pk=building_id)

        buildings = []
        totals = {"total": 0, "occupied": 0, "vacant": 0, "under_maintenance": 0}
        for b in qs:
            buildings.append({
                "id": b.id,
                "name": b.name,
                "property_type": b.get_property_type_display(),
                "total": b.total,
                "occupied": b.occ,
                "vacant": b.vacant,
                "under_maintenance": b.maintenance,
                "rate": round(b.occ / b.total * 100, 1) if b.total else 0,
            })
            totals["total"] += b.total
            totals["occupied"] += b.occ
            totals["vacant"] += b.vacant
            totals["under_maintenance"] += b.maintenance
        totals["rate"] = (
            round(totals["occupied"] / totals["total"] * 100, 1) if totals["total"] else 0
        )
        return Response({
            "building": _building_meta(building_id),
            "total_units": totals["total"],
            "totals": totals,
            "buildings": buildings,
        })


class MoveInOutLogView(APIView):
    """GET /api/reports/move-log/?building=&status=&from=&to=

    With ``from``/``to`` (YYYY-MM-DD), lists tenancies that moved in or out in
    that window; without them, every tenancy, most recent move first.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = _tenant_qs(request)
        start, end = _date_param(request, "from"), _date_param(request, "to")
        if start or end:
            move_in, move_out = Q(), Q(move_out_date__isnull=False)
            if start:
                move_in &= Q(move_in_date__gte=start)
                move_out &= Q(move_out_date__gte=start)
            if end:
                move_in &= Q(move_in_date__lte=end)
                move_out &= Q(move_out_date__lte=end)
            qs = qs.filter(move_in | move_out)

        log = []
        for t in qs:
            last_event = max(filter(None, [t.move_in_date, t.move_out_date]))
            log.append({
                "tenant_id": t.id,
                "tenant": t.full_name,
                "unit": _unit_name(t.unit),
                "move_in": t.move_in_date.isoformat(),
                "move_out": t.move_out_date.isoformat() if t.move_out_date else None,
                "status": t.get_status_display(),
                "_sort": last_event,
            })
        log.sort(key=lambda e: e.pop("_sort"), reverse=True)
        return Response({
            "building": _building_meta(building_param(request)),
            "count": len(log),
            "moved_in": sum(
                1 for e in log
                if (not start or e["move_in"] >= start.isoformat())
                and (not end or e["move_in"] <= end.isoformat())
            ),
            "moved_out": sum(
                1 for e in log
                if e["move_out"]
                and (not start or e["move_out"] >= start.isoformat())
                and (not end or e["move_out"] <= end.isoformat())
            ),
            "entries": log,
        })


class ProfitLossReportView(APIView):
    """GET /api/reports/profit-loss/?mode=monthly|annual&month=&year=&building="""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        mode = request.query_params.get("mode", "monthly")
        if mode not in ("monthly", "annual"):
            raise ValidationError({"mode": "Use monthly or annual."})
        building_id = building_param(request)
        today = _today()

        if mode == "annual":
            year = int_param(request, "year", today.year, lo=2000, hi=2100)
            rows = []
            grand_income = ZERO
            grand_expenses = ZERO
            for m in range(1, 13):
                income = income_total(m, year, building_id=building_id)
                expenses = sum(
                    (r["total"] for r in expense_by_category(m, year, building_id=building_id)),
                    ZERO,
                )
                rows.append({
                    "month": m, "income": float(income), "expenses": float(expenses),
                    "net": float(income - expenses),
                })
                grand_income += income
                grand_expenses += expenses
            return Response({
                "mode": "annual", "year": year,
                "building": building_id,
                "building_name": (_building_meta(building_id) or {}).get("name"),
                "grand_income": float(grand_income), "grand_expenses": float(grand_expenses),
                "grand_net": float(grand_income - grand_expenses), "monthly": rows,
            })

        month, year = period_params(request, today)
        lines = income_lines(month, year, building_id=building_id)
        categories = expense_by_category(month, year, building_id=building_id)
        total_expenses = sum((r["total"] for r in categories), ZERO)
        return Response({
            "mode": "monthly", "period": f"{month}/{year}",
            "building": building_id,
            "building_name": (_building_meta(building_id) or {}).get("name"),
            "income": float(lines["total"]),
            "income_breakdown": _income_breakdown(lines),
            "total_expenses": float(total_expenses),
            "net_profit": float(lines["total"] - total_expenses),
            "expense_breakdown": [
                {"category": r["category"], "amount": float(r["total"])} for r in categories
            ],
        })


def _income_breakdown(lines) -> list[dict]:
    """Income lines worth printing — zero lines are left out."""
    items = [
        ("Residential rent", lines["residential_rent"]),
        ("Commercial rent (excl. VAT)", lines["commercial_rent"]),
        ("Late fees", lines["late_fees"]),
        ("Other income", lines["other_income"]),
        *lines["manual_income"],
        ("Credits and refunds", lines["credit_adjustment"]),
    ]
    return [{"label": label, "amount": float(amount)} for label, amount in items if amount]


class TrialBalanceView(APIView):
    """GET /api/reports/trial-balance/?month=&year=&building=

    Sourced from JournalLine so total_debit == total_credit exactly.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.ledger.models import JournalLine

        month, year = period_params(request, _today())
        building_id = building_param(request)

        lines_qs = JournalLine.objects.filter(
            entry__period_month=month,
            entry__period_year=year,
            entry__is_posted=True,
        )
        if building_id:
            lines_qs = lines_qs.filter(entry__building_id=building_id)
        lines_qs = lines_qs.values("account__code", "account__name").annotate(
            total_debit=Sum("debit"),
            total_credit=Sum("credit"),
        ).order_by("account__code")

        accounts = []
        total_debit = ZERO
        total_credit = ZERO

        for row in lines_qs:
            dr = money(row["total_debit"])
            cr = money(row["total_credit"])
            total_debit += dr
            total_credit += cr
            accounts.append({
                "account": f"{row['account__code']} {row['account__name']}",
                "debit": float(dr),
                "credit": float(cr),
            })

        return Response({
            "period": f"{month}/{year}",
            "building": building_id,
            "accounts": accounts,
            "total_debit": float(total_debit),
            "total_credit": float(total_credit),
            "is_balanced": abs(total_debit - total_credit) < Decimal("0.01"),
        })


class ExpenseBreakdownReportView(APIView):
    """GET /api/reports/expense-breakdown/?month=&year=&building=

    Income beside it is the P&L's income for the same period, so the expense
    ratio is expenses over the income the P&L reports — not gross receipts.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        month, year = period_params(request, _today())
        building_id = building_param(request)

        categories = expense_by_category(month, year, building_id=building_id)
        grand_total = sum((r["total"] for r in categories), ZERO)
        rows = [
            {
                "category": r["category"],
                "total": float(r["total"]),
                "count": r["count"],
                "percentage": (
                    round(float(r["total"] / grand_total * 100), 1) if grand_total else 0.0
                ),
            }
            for r in categories
        ]
        income = income_total(month, year, building_id=building_id)
        return Response({
            "period": f"{month}/{year}",
            "building": building_id,
            "categories": rows,
            "total_expenses": float(grand_total),
            "total_income": float(income),
            "expense_ratio": (
                round(float(grand_total / income * 100), 1) if income > 0 else 0.0
            ),
        })
