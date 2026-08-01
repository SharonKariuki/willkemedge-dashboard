"""
Dashboard + Reports API — updated for real-time arrears, due dates per tenant,
move-out alerts, maintenance alerts, and expiring-lease alerts.
"""
from decimal import Decimal

from django.db.models import Case, Count, DecimalField, F, Q, Sum, When
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.buildings.models import (
    OCCUPIED_UNIT_STATUSES,
    Building,
    Unit,
    UnitClassification,
    UnitStatus,
)
from apps.payments.models import Arrears, Payment, PaymentType
from apps.payments.tax_service import TAX_RATE_BUSINESS
from apps.tenants.models import Tenant, TenantStatus


class DashboardSummaryView(APIView):
    """
    GET /api/dashboard/summary/
    Returns all KPI data, chart data, recent payments, and real-time alerts.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        now = timezone.now()
        current_month = now.month
        current_year = now.year
        today = now.date()

        # --- KPI cards ---
        total_units = Unit.objects.count()
        vacant = Unit.objects.filter(status=UnitStatus.VACANT).count()
        under_maintenance = Unit.objects.filter(
            status=UnitStatus.UNDER_MAINTENANCE
        ).count()
        # A unit under renovation has no tenant — it is neither vacant-available
        # nor occupied, so count only genuinely tenanted units as occupied.
        occupied = Unit.objects.filter(status__in=OCCUPIED_UNIT_STATUSES).count()
        active_tenants = Tenant.objects.filter(status=TenantStatus.ACTIVE).count()

        # Real-time arrears: sum all uncleared balances
        total_arrears = Arrears.objects.filter(is_cleared=False).aggregate(
            total=Sum("balance")
        )["total"] or Decimal("0")

        # --- Monthly rent collection ---
        # Expected rent is stored VAT-exclusive (base) for commercial units, but
        # commercial tenants pay rent + 16% VAT as one figure. Gross the expected
        # up so it shares the VAT-inclusive basis of the cash actually received —
        # otherwise a fully-paying commercial portfolio reads above 100%.
        vat_multiplier = Decimal("1") + TAX_RATE_BUSINESS
        expected = Tenant.objects.filter(status=TenantStatus.ACTIVE).aggregate(
            total=Sum(
                Case(
                    When(
                        unit__classification=UnitClassification.BUSINESS,
                        then=F("monthly_rent") * vat_multiplier,
                    ),
                    default=F("monthly_rent"),
                    output_field=DecimalField(max_digits=12, decimal_places=2),
                )
            )
        )["total"] or Decimal("0")

        # Collection measures RENT against rent owed — deposits (a liability) and
        # other payment types are not rent collection.
        collected = Payment.objects.filter(
            payment_type=PaymentType.RENT,
            period_month=current_month,
            period_year=current_year,
            voided_at__isnull=True,
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")

        collection_pct = (
            round(float(collected) / float(expected) * 100, 1) if expected else 0.0
        )

        # --- This month stats: % vs last month ---
        last_month = current_month - 1 if current_month > 1 else 12
        last_year = current_year if current_month > 1 else current_year - 1
        last_month_collected = Payment.objects.filter(
            payment_type=PaymentType.RENT,
            period_month=last_month, period_year=last_year,
            voided_at__isnull=True,
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")

        # --- 12-month income trend (income excludes refundable deposits) ---
        # Net of VAT and void, on exactly the basis the P&L and the annual
        # income report use, so "income" means one thing across the dashboard
        # rather than gross here and net there.
        from apps.dashboard.views_reports import INCOME_PAYMENT_FILTER, _net_income_sum

        income_trend = []
        for i in range(11, -1, -1):
            total_months = current_year * 12 + (current_month - 1) - i
            y, m0 = divmod(total_months, 12)
            m = m0 + 1
            month_total = Payment.objects.filter(
                INCOME_PAYMENT_FILTER, period_month=m, period_year=y
            ).aggregate(total=_net_income_sum())["total"] or 0
            income_trend.append({
                "month": f"{y}-{m:02d}",
                "amount": float(month_total),
            })

        # --- Occupancy breakdown (slices sum to total_units) ---
        occupancy = {
            "vacant": vacant,
            "paid": Unit.objects.filter(status=UnitStatus.OCCUPIED_PAID).count(),
            "partial": Unit.objects.filter(status=UnitStatus.OCCUPIED_PARTIAL).count(),
            "unpaid": Unit.objects.filter(status=UnitStatus.OCCUPIED_UNPAID).count(),
            "arrears": Unit.objects.filter(status=UnitStatus.ARREARS).count(),
            "under_maintenance": under_maintenance,
        }

        # --- Per-building breakdown ---
        buildings = []
        for b in Building.objects.annotate(
            unit_count=Count("units"),
            occupied_count=Count(
                "units", filter=Q(units__status__in=OCCUPIED_UNIT_STATUSES)
            ),
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
        recent_list = []
        for p in recent:
            try:
                recent_list.append({
                    "id": p.id,
                    "tenant_name": p.tenant.full_name,
                    "unit_label": p.tenant.unit.label,
                    "building_name": p.tenant.unit.building.name,
                    "amount": float(p.amount),
                    "source": p.source,
                    "payment_date": p.payment_date.isoformat(),
                    "reference": p.reference,
                })
            except Exception:
                pass

        # --- Real-time Alerts (overdue, partial, move-out, maintenance) ---
        alerts = []

        # 1. Overdue tenants with arrears — show each with amount & due date
        overdue_qs = (
            Arrears.objects.filter(is_cleared=False)
            .select_related("tenant", "tenant__unit", "tenant__unit__building")
            .order_by("-balance")[:8]
        )
        for a in overdue_qs:
            # Use tenant's custom due_day or default to 5th
            due_day = getattr(a.tenant, "due_day", 5)
            due_date_str = f"{due_day:02d}/{a.period_month:02d}/{a.period_year}"
            alerts.append({
                "type": "overdue",
                "message": (
                    f"{a.tenant.full_name} owes KES {a.balance:,.0f} "
                    f"(Due {due_date_str}) — "
                    f"{a.tenant.unit.building.name} {a.tenant.unit.label}"
                ),
                "tenant_id": a.tenant_id,
            })


        # 2. Partial payments
        partial_units = (
            Unit.objects.filter(status=UnitStatus.OCCUPIED_PARTIAL)
            .select_related("building")[:5]
        )
        for u in partial_units:
            alerts.append({
                "type": "partial",
                "message": f"{u.building.name} — {u.label} has a partial payment this month",
                "unit_id": u.id,
            })

        # 3. Move-out notices: tenants with move_out_date set in next 30 days
        move_out_soon = Tenant.objects.filter(
            status=TenantStatus.ACTIVE,
            move_out_date__isnull=False,
            move_out_date__gte=today,
        ).select_related("unit", "unit__building")[:5]
        for t in move_out_soon:
            days_left = (t.move_out_date - today).days
            alerts.append({
                "type": "move_out",
                "message": (
                    f"{t.full_name} ({t.unit.building.name} {t.unit.label}) "
                    f"is moving out in {days_left} day{'s' if days_left != 1 else ''}"
                ),
                "tenant_id": t.id,
            })

        # 4. Expiring leases: tenants who have been active > 11 months (no move-out set)
        from datetime import timedelta
        lease_threshold = today - timedelta(days=335)
        expiring = Tenant.objects.filter(
            status=TenantStatus.ACTIVE,
            move_out_date__isnull=True,
            move_in_date__lte=lease_threshold,
        ).select_related("unit", "unit__building")[:3]
        for t in expiring:
            alerts.append({
                "type": "expiring_lease",
                "message": (
                    f"{t.full_name} ({t.unit.building.name} {t.unit.label}) "
                    f"has been a tenant since {t.move_in_date} — lease renewal due"
                ),
                "tenant_id": t.id,
            })

        return Response({
            "kpis": {
                "total_units": total_units,
                "occupied": occupied,
                "vacant": vacant,
                "under_maintenance": under_maintenance,
                "active_tenants": active_tenants,
                "total_arrears": float(total_arrears),
                "collection_expected": float(expected),
                "collection_received": float(collected),
                "collection_percentage": float(collection_pct),
                "last_month_received": float(last_month_collected),
            },
            "income_trend": income_trend,
            "occupancy": occupancy,
            "buildings": buildings,
            "recent_payments": recent_list,
            "alerts": alerts,
        })
