"""Dashboard views_reports — all reporting endpoints."""
from collections import defaultdict
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.buildings.models import Building, Unit, UnitStatus
from apps.expenses.models import Expense
from apps.payments.models import Arrears, Payment
from apps.tenants.models import Tenant, TenantStatus


class MonthlyCollectionReportView(APIView):
    """GET /api/reports/monthly-collection/?month=4&year=2026"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        now = timezone.now()
        month = int(request.query_params.get("month", now.month))
        year = int(request.query_params.get("year", now.year))

        payments = Payment.objects.filter(
            period_month=month, period_year=year
        ).select_related("tenant", "tenant__unit", "tenant__unit__building").order_by(
            "tenant__unit__building__name", "tenant__unit__label"
        )

        rows = []
        for p in payments:
            rows.append({
                "tenant": p.tenant.full_name,
                "unit": f"{p.tenant.unit.building.name} — {p.tenant.unit.label}",
                "amount": float(p.amount),
                "source": p.get_source_display(),
                "date": p.payment_date.isoformat(),
                "reference": p.reference,
            })

        total = sum(r["amount"] for r in rows)
        return Response({"period": f"{month}/{year}", "total": total, "count": len(rows), "payments": rows})


class AnnualIncomeSummaryView(APIView):
    """GET /api/reports/annual-income/?year=2026"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        year = int(request.query_params.get("year", timezone.now().year))
        monthly = []
        grand_total = Decimal("0")
        for m in range(1, 13):
            total = Payment.objects.filter(period_month=m, period_year=year).aggregate(total=Sum("amount"))["total"] or Decimal("0")
            monthly.append({"month": m, "total": float(total)})
            grand_total += total
        return Response({"year": year, "grand_total": float(grand_total), "monthly": monthly})


class ArrearsReportView(APIView):
    """GET /api/reports/arrears/"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        arrears = Arrears.objects.filter(is_cleared=False).select_related(
            "tenant", "tenant__unit", "tenant__unit__building"
        ).order_by("-balance")

        rows = []
        for a in arrears:
            rows.append({
                "tenant": a.tenant.full_name,
                "unit": f"{a.tenant.unit.building.name} — {a.tenant.unit.label}",
                "period": f"{a.period_month}/{a.period_year}",
                "expected": float(a.expected_rent),
                "paid": float(a.amount_paid),
                "balance": float(a.balance),
            })

        total_balance = sum(r["balance"] for r in rows)
        return Response({"total_balance": total_balance, "count": len(rows), "arrears": rows})


class TenantPaymentHistoryView(APIView):
    """GET /api/reports/tenant-history/<tenant_id>/"""
    permission_classes = [IsAuthenticated]

    def get(self, request, tenant_id):
        tenant = Tenant.objects.select_related("unit", "unit__building").get(pk=tenant_id)
        payments = Payment.objects.filter(tenant=tenant).order_by("period_year", "period_month")

        monthly = defaultdict(float)
        for p in payments:
            key = f"{p.period_year}-{p.period_month:02d}"
            monthly[key] += float(p.amount)

        chart_data = [
            {"month": k, "paid": v, "expected": float(tenant.monthly_rent)}
            for k, v in sorted(monthly.items())
        ]

        return Response({
            "tenant": {
                "id": tenant.id,
                "name": tenant.full_name,
                "unit": f"{tenant.unit.building.name} — {tenant.unit.label}",
                "monthly_rent": float(tenant.monthly_rent),
            },
            "chart_data": chart_data,
            "total_paid": sum(v for v in monthly.values()),
        })


class OccupancyHistoryView(APIView):
    """GET /api/reports/occupancy/"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        total = Unit.objects.count()
        buildings = []
        for b in Building.objects.annotate(
            total=Count("units"),
            occ=Count("units", filter=~Q(units__status=UnitStatus.VACANT)),
        ).order_by("name"):
            buildings.append({
                "name": b.name,
                "total": b.total,
                "occupied": b.occ,
                "rate": round(b.occ / b.total * 100, 1) if b.total else 0,
            })
        return Response({"total_units": total, "buildings": buildings})


class MoveInOutLogView(APIView):
    """GET /api/reports/move-log/"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        tenants = Tenant.objects.select_related("unit", "unit__building").order_by("-move_in_date")[:50]
        log = []
        for t in tenants:
            log.append({
                "tenant": t.full_name,
                "unit": f"{t.unit.building.name} — {t.unit.label}",
                "move_in": t.move_in_date.isoformat(),
                "move_out": t.move_out_date.isoformat() if t.move_out_date else None,
                "status": t.get_status_display(),
            })
        return Response({"entries": log})


class ProfitLossReportView(APIView):
    """GET /api/reports/profit-loss/?month=4&year=2026"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        mode = request.query_params.get("mode", "monthly")
        building_id = request.query_params.get("building")
        now = timezone.now()

        payments_qs = Payment.objects.all()
        expenses_qs_all = Expense.objects.all()
        if building_id:
            payments_qs = payments_qs.filter(tenant__unit__building_id=building_id)
            expenses_qs_all = expenses_qs_all.filter(building_id=building_id)

        if mode == "annual":
            year = int(request.query_params.get("year", now.year))
            rows = []
            grand_income = Decimal("0")
            grand_expenses = Decimal("0")
            for m in range(1, 13):
                income = payments_qs.filter(period_month=m, period_year=year).aggregate(total=Sum("amount"))["total"] or Decimal("0")
                exp_total = expenses_qs_all.filter(period_month=m, period_year=year).aggregate(total=Sum("amount"))["total"] or Decimal("0")
                rows.append({"month": m, "income": float(income), "expenses": float(exp_total), "net": float(income - exp_total)})
                grand_income += income
                grand_expenses += exp_total
            return Response({
                "mode": "annual", "year": year,
                "building": int(building_id) if building_id else None,
                "grand_income": float(grand_income), "grand_expenses": float(grand_expenses),
                "grand_net": float(grand_income - grand_expenses), "monthly": rows,
            })

        month = int(request.query_params.get("month", now.month))
        year = int(request.query_params.get("year", now.year))
        income = payments_qs.filter(period_month=month, period_year=year).aggregate(total=Sum("amount"))["total"] or Decimal("0")
        expenses_qs = expenses_qs_all.filter(period_month=month, period_year=year).values("category__name").annotate(total=Sum("amount")).order_by("-total")
        expense_rows = [{"category": row["category__name"], "amount": float(row["total"])} for row in expenses_qs]
        total_expenses = sum(r["amount"] for r in expense_rows)
        return Response({
            "mode": "monthly", "period": f"{month}/{year}",
            "building": int(building_id) if building_id else None,
            "income": float(income), "total_expenses": total_expenses,
            "net_profit": float(income) - total_expenses, "expense_breakdown": expense_rows,
        })


class TrialBalanceView(APIView):
    """GET /api/reports/trial-balance/?month=4&year=2026"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        now = timezone.now()
        month = int(request.query_params.get("month", now.month))
        year = int(request.query_params.get("year", now.year))
        building_id = request.query_params.get("building")

        payments_qs = Payment.objects.filter(period_month=month, period_year=year)
        arrears_qs = Arrears.objects.filter(period_month=month, period_year=year)
        tenants_qs = Tenant.objects.filter(status=TenantStatus.ACTIVE)
        expenses_base = Expense.objects.filter(period_month=month, period_year=year)

        if building_id:
            payments_qs = payments_qs.filter(tenant__unit__building_id=building_id)
            arrears_qs = arrears_qs.filter(tenant__unit__building_id=building_id)
            tenants_qs = tenants_qs.filter(unit__building_id=building_id)
            expenses_base = expenses_base.filter(building_id=building_id)

        collected = payments_qs.aggregate(total=Sum("amount"))["total"] or Decimal("0")
        expected = tenants_qs.aggregate(total=Sum("monthly_rent"))["total"] or Decimal("0")
        accounts_receivable = arrears_qs.filter(is_cleared=False).aggregate(total=Sum("balance"))["total"] or Decimal("0")

        expenses_qs = expenses_base.values("category__name").annotate(total=Sum("amount")).order_by("category__name")
        expense_rows = [{"account": row["category__name"], "debit": float(row["total"]), "credit": 0.0} for row in expenses_qs]
        total_expenses = sum(r["debit"] for r in expense_rows)

        accounts = [
            {"account": "Cash / Bank (collected)", "debit": float(collected), "credit": 0.0},
            {"account": "Accounts Receivable (Arrears)", "debit": float(accounts_receivable), "credit": 0.0},
            *expense_rows,
            {"account": "Cash / Bank (expenses paid)", "debit": 0.0, "credit": total_expenses},
            {"account": "Rent Revenue", "debit": 0.0, "credit": float(expected)},
        ]

        total_debit = sum(a["debit"] for a in accounts)
        total_credit = sum(a["credit"] for a in accounts)
        is_balanced = abs(total_debit - total_credit) < 0.01

        return Response({
            "period": f"{month}/{year}",
            "building": int(building_id) if building_id else None,
            "accounts": accounts,
            "total_debit": round(total_debit, 2),
            "total_credit": round(total_credit, 2),
            "is_balanced": is_balanced,
        })


class ExpenseBreakdownReportView(APIView):
    """GET /api/reports/expense-breakdown/?month=4&year=2026"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        now = timezone.now()
        month = int(request.query_params.get("month", now.month))
        year = int(request.query_params.get("year", now.year))
        building_id = request.query_params.get("building")

        expenses_base = Expense.objects.filter(period_month=month, period_year=year)
        payments_qs = Payment.objects.filter(period_month=month, period_year=year)
        if building_id:
            expenses_base = expenses_base.filter(building_id=building_id)
            payments_qs = payments_qs.filter(tenant__unit__building_id=building_id)

        expenses_qs = expenses_base.values("category__name").annotate(total=Sum("amount"), count=Count("id")).order_by("-total")
        rows = [{"category": row["category__name"], "total": float(row["total"]), "count": row["count"]} for row in expenses_qs]
        grand_total = sum(r["total"] for r in rows)
        for r in rows:
            r["percentage"] = round(r["total"] / grand_total * 100, 1) if grand_total else 0.0

        income = payments_qs.aggregate(total=Sum("amount"))["total"] or Decimal("0")
        return Response({
            "period": f"{month}/{year}",
            "building": int(building_id) if building_id else None,
            "categories": rows,
            "total_expenses": grand_total,
            "total_income": float(income),
            "expense_ratio": round(grand_total / float(income) * 100, 1) if income else 0.0,
        })
