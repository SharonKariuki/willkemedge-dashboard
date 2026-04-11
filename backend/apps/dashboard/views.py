"""
Dashboard + Reports API.

Single /api/dashboard/summary/ call returns all KPIs, chart data, recent
payments, and alerts. Report endpoints return filtered data for each report type.
"""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.buildings.models import Building, Unit, UnitStatus
from apps.payments.models import Arrears, Payment
from apps.tenants.models import Tenant, TenantStatus


class DashboardSummaryView(APIView):
    """
    GET /api/dashboard/summary/

    Returns everything the dashboard page needs in a single call:
    - KPI cards (units, tenants, arrears totals)
    - Monthly collection progress
    - 12-month income trend
    - Occupancy breakdown
    - Recent payments (last 10)
    - Alerts (overdue, partial, upcoming move-outs)
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        now = timezone.now()
        current_month = now.month
        current_year = now.year

        # --- KPI cards ---
        total_units = Unit.objects.count()
        vacant = Unit.objects.filter(status=UnitStatus.VACANT).count()
        occupied = total_units - vacant
        active_tenants = Tenant.objects.filter(status=TenantStatus.ACTIVE).count()

        total_arrears = Arrears.objects.filter(is_cleared=False).aggregate(
            total=Sum("balance")
        )["total"] or Decimal("0")

        # --- Monthly collection ---
        expected = Tenant.objects.filter(status=TenantStatus.ACTIVE).aggregate(
            total=Sum("monthly_rent")
        )["total"] or Decimal("0")

        collected = Payment.objects.filter(
            period_month=current_month,
            period_year=current_year,
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")

        collection_pct = (
            round(collected / expected * 100, 1) if expected else Decimal("0")
        )

        # --- 12-month income trend ---
        income_trend = []
        for i in range(11, -1, -1):
            d = date(current_year, current_month, 1) - timedelta(days=i * 30)
            m, y = d.month, d.year
            month_total = Payment.objects.filter(
                period_month=m, period_year=y
            ).aggregate(total=Sum("amount"))["total"] or 0
            income_trend.append({
                "month": f"{y}-{m:02d}",
                "amount": float(month_total),
            })

        # --- Occupancy breakdown ---
        occupancy = {
            "vacant": vacant,
            "paid": Unit.objects.filter(status=UnitStatus.OCCUPIED_PAID).count(),
            "partial": Unit.objects.filter(status=UnitStatus.OCCUPIED_PARTIAL).count(),
            "unpaid": Unit.objects.filter(status=UnitStatus.OCCUPIED_UNPAID).count(),
            "arrears": Unit.objects.filter(status=UnitStatus.ARREARS).count(),
        }

        # --- Per-building breakdown ---
        buildings = []
        for b in Building.objects.annotate(
            unit_count=Count("units"),
            occupied_count=Count("units", filter=~Q(units__status=UnitStatus.VACANT)),
        ).order_by("name"):
            buildings.append({
                "id": b.id,
                "name": b.name,
                "total": b.unit_count,
                "occupied": b.occupied_count,
                "vacant": b.unit_count - b.occupied_count,
            })

        # --- Recent payments ---
        recent = Payment.objects.select_related(
            "tenant", "tenant__unit", "tenant__unit__building"
        ).order_by("-created_at")[:10]
        recent_list = [
            {
                "id": p.id,
                "tenant_name": p.tenant.full_name,
                "unit_label": p.tenant.unit.label,
                "building_name": p.tenant.unit.building.name,
                "amount": float(p.amount),
                "source": p.source,
                "payment_date": p.payment_date.isoformat(),
                "reference": p.reference,
            }
            for p in recent
        ]

        # --- Alerts ---
        alerts = []

        # Overdue tenants (arrears not cleared)
        overdue = Arrears.objects.filter(is_cleared=False).select_related(
            "tenant", "tenant__unit"
        ).order_by("-balance")[:5]
        for a in overdue:
            alerts.append({
                "type": "overdue",
                "message": f"{a.tenant.full_name} owes KES {a.balance:,.0f} for {a.period_month}/{a.period_year}",
                "tenant_id": a.tenant_id,
            })

        # Units with partial payment
        partial_units = Unit.objects.filter(
            status=UnitStatus.OCCUPIED_PARTIAL
        ).select_related("building")[:5]
        for u in partial_units:
            alerts.append({
                "type": "partial",
                "message": f"{u.building.name} — {u.label} has partial payment",
                "unit_id": u.id,
            })

        return Response({
            "kpis": {
                "total_units": total_units,
                "occupied": occupied,
                "vacant": vacant,
                "active_tenants": active_tenants,
                "total_arrears": float(total_arrears),
                "collection_expected": float(expected),
                "collection_received": float(collected),
                "collection_percentage": float(collection_pct),
            },
            "income_trend": income_trend,
            "occupancy": occupancy,
            "buildings": buildings,
            "recent_payments": recent_list,
            "alerts": alerts,
        })


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
        return Response({
            "period": f"{month}/{year}",
            "total": total,
            "count": len(rows),
            "payments": rows,
        })


class AnnualIncomeSummaryView(APIView):
    """GET /api/reports/annual-income/?year=2026"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        year = int(request.query_params.get("year", timezone.now().year))

        monthly = []
        grand_total = Decimal("0")
        for m in range(1, 13):
            total = Payment.objects.filter(
                period_month=m, period_year=year
            ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
            monthly.append({"month": m, "total": float(total)})
            grand_total += total

        return Response({
            "year": year,
            "grand_total": float(grand_total),
            "monthly": monthly,
        })


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
        return Response({
            "total_balance": total_balance,
            "count": len(rows),
            "arrears": rows,
        })


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
        occupancy = {}
        for s in UnitStatus:
            occupancy[s.value] = Unit.objects.filter(status=s.value).count()

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

        return Response({
            "total_units": total,
            "breakdown": occupancy,
            "buildings": buildings,
        })


class MoveInOutLogView(APIView):
    """GET /api/reports/move-log/"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        tenants = Tenant.objects.select_related(
            "unit", "unit__building"
        ).order_by("-move_in_date")[:50]

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
