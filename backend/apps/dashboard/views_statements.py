"""Reports the Reports page has always had tabs for but no endpoint behind.

Rent Balances, Overpayments, Expiring Leases, Vacant Units, Tenant Statement,
Unit Statement and Landlord Statement all called routes that were never
written, so each tab could only ever show its error state. Every figure here
comes from the same rent roll (``monthly_ledger`` / ``report_data``) and the
same income and expense functions the P&L uses, so a balance or a net figure
printed here is the one printed everywhere else.
"""
from __future__ import annotations

import datetime as _dt
from decimal import Decimal

from django.db.models import Max
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.buildings.models import PropertyType, Unit, UnitStatus
from apps.payments.monthly_ledger import build_monthly_ledger
from apps.tenants.models import Tenant, TenantStatus

from .report_data import (
    ZERO,
    building_param,
    expense_by_category,
    income_lines,
    int_param,
    money,
    month_rows,
    period_params,
)
from .views_reports import (
    CURRENT_STATUSES,
    _building_meta,
    _period_range,
    _today,
    _unit_name,
)


def _f(value) -> float:
    return float(money(value))


class RentBalancesReportView(APIView):
    """GET /api/reports/rent-balances/?month=&year=&building=&status=

    One row per tenancy for the month: balance brought forward, what the month
    charged (rent, VAT, water and other charges, refunds), what came in, credits
    given, and the balance it closed on. Across every row::

        brought_forward + charged − paid − credits = balance

    ``status`` narrows to ``owing`` (balance above zero), ``credit`` (below
    zero) or ``square``.
    """
    permission_classes = [IsAuthenticated]

    STATUSES = {"all", "owing", "credit", "square"}

    def get(self, request):
        month, year = period_params(request, _today())
        building_id = building_param(request)
        wanted = request.query_params.get("status", "all")
        if wanted not in self.STATUSES:
            raise ValidationError({"status": "Use all, owing, credit or square."})

        rows = []
        totals = dict.fromkeys(
            ("brought_forward", "charged", "paid", "credits", "balance"), ZERO
        )
        for tenant, row in month_rows(month, year, building_id=building_id):
            balance = row["balance"]
            if (
                (wanted == "owing" and balance <= 0)
                or (wanted == "credit" and balance >= 0)
                or (wanted == "square" and balance != 0)
            ):
                continue
            for key in totals:
                totals[key] += row[key]
            rows.append({
                "tenant_id": tenant.id,
                "tenant": tenant.full_name,
                "unit": _unit_name(tenant.unit),
                "monthly_rent": _f(tenant.monthly_rent),
                "brought_forward": _f(row["brought_forward"]),
                "rent": _f(row["rent"] + row["vat"]),
                "other_charges": _f(row["other_charges"] + row["refunds"]),
                "charged": _f(row["charged"]),
                "paid": _f(row["paid"]),
                "credits": _f(row["credits"]),
                "balance": _f(balance),
                "status": row["status"],
            })

        owing = sum((Decimal(str(r["balance"])) for r in rows if r["balance"] > 0), ZERO)
        in_credit = sum((-Decimal(str(r["balance"])) for r in rows if r["balance"] < 0), ZERO)
        return Response({
            "period": f"{month}/{year}",
            "building": _building_meta(building_id),
            "count": len(rows),
            "totals": {key: _f(value) for key, value in totals.items()},
            "total_outstanding": _f(owing),
            "total_in_credit": _f(in_credit),
            "balances": rows,
        })


class RentOverpaymentsReportView(APIView):
    """GET /api/reports/rent-overpayments/?month=&year=&building=

    Tenants who closed the month in credit — paid more than they owed — and by
    how much. The credit carries into next month and is the same negative
    balance their statement shows.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        month, year = period_params(request, _today())
        building_id = building_param(request)

        rows = []
        for tenant, row in month_rows(month, year, building_id=building_id):
            if row["balance"] >= 0:
                continue
            rows.append({
                "tenant_id": tenant.id,
                "tenant": tenant.full_name,
                "unit": _unit_name(tenant.unit),
                "status": tenant.get_status_display(),
                "expected": _f(row["charged"]),
                "paid": _f(row["paid"]),
                "overpaid": _f(-row["balance"]),
            })
        rows.sort(key=lambda r: -r["overpaid"])
        return Response({
            "period": f"{month}/{year}",
            "building": _building_meta(building_id),
            "count": len(rows),
            "total_overpaid": _f(sum((Decimal(str(r["overpaid"])) for r in rows), ZERO)),
            "overpayments": rows,
        })


def _next_anniversary(move_in: _dt.date, today: _dt.date) -> _dt.date:
    """The next date the tenancy completes a whole year — today counts."""
    years = today.year - move_in.year
    for offset in (years, years + 1):
        try:
            candidate = move_in.replace(year=move_in.year + offset)
        except ValueError:  # 29 February in a non-leap year
            candidate = _dt.date(move_in.year + offset, 3, 1)
        if candidate >= today and offset > 0:
            return candidate
    return _dt.date(today.year + 1, move_in.month, min(move_in.day, 28))


class ExpiringLeasesReportView(APIView):
    """GET /api/reports/expiring-leases/?days=60&building=

    Leases here run a year at a time from the move-in date and there is no
    separate lease-end field, so a lease "expires" on each anniversary of the
    move-in. Lists current tenants whose next anniversary falls within ``days``
    (default 60), and every tenant who has given notice, with the date they
    said they would leave.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        today = _today()
        days = int_param(request, "days", 60, lo=1, hi=366)
        building_id = building_param(request)

        qs = Tenant.objects.select_related("unit", "unit__building").prefetch_related(
            "unit__combined_units"
        ).filter(status__in=CURRENT_STATUSES, move_in_date__lte=today)
        if building_id:
            qs = qs.filter(unit__building_id=building_id)

        rows = []
        for tenant in qs:
            renewal = _next_anniversary(tenant.move_in_date, today)
            days_left = (renewal - today).days
            on_notice = tenant.status == TenantStatus.NOTICE_GIVEN
            if not on_notice and days_left > days:
                continue
            months_active = (
                (today.year - tenant.move_in_date.year) * 12
                + today.month - tenant.move_in_date.month
                - (1 if today.day < tenant.move_in_date.day else 0)
            )
            leaving = tenant.intended_move_out_date or tenant.move_out_date
            rows.append({
                "tenant_id": tenant.id,
                "tenant": tenant.full_name,
                "unit": _unit_name(tenant.unit),
                "phone": tenant.phone,
                "move_in_date": tenant.move_in_date.isoformat(),
                "months_active": max(months_active, 0),
                "renewal_date": renewal.isoformat(),
                "days_to_renewal": days_left,
                "leaving_on": leaving.isoformat() if leaving else None,
                "status": "Notice given" if on_notice else "Renewal due",
            })
        rows.sort(key=lambda r: (r["status"] != "Notice given", r["days_to_renewal"]))
        return Response({
            "days": days,
            "building": _building_meta(building_id),
            "count": len(rows),
            "leases": rows,
        })


class VacantUnitsReportView(APIView):
    """GET /api/reports/vacant-units/?building=&status=vacant|under_maintenance|all

    Lettable units with no tenant in them. A unit folded into a combined space
    is let with its head, so only the head is listed (as "MCG05 + MCG06");
    units on farms and expense-only properties are not let at all and are left
    out. Rent is the unit's asking rent, before VAT for a commercial unit.
    """
    permission_classes = [IsAuthenticated]

    STATUS_MAP = {
        "vacant": (UnitStatus.VACANT,),
        "under_maintenance": (UnitStatus.UNDER_MAINTENANCE,),
        "all": (UnitStatus.VACANT, UnitStatus.UNDER_MAINTENANCE),
    }

    def get(self, request):
        wanted = request.query_params.get("status", "all")
        if wanted not in self.STATUS_MAP:
            raise ValidationError({"status": "Use vacant, under_maintenance or all."})
        building_id = building_param(request)

        qs = (
            Unit.objects.filter(
                status__in=self.STATUS_MAP[wanted],
                combined_into__isnull=True,
                building__property_type=PropertyType.RENTAL,
            )
            .select_related("building")
            .prefetch_related("combined_units")
            .annotate(last_move_out=Max("tenants__move_out_date"))
            .order_by("building__name", "floor", "label")
        )
        if building_id:
            qs = qs.filter(building_id=building_id)

        today = _today()
        rows = []
        potential = ZERO
        for unit in qs:
            rent = money(unit.monthly_rent) + sum(
                (money(u.monthly_rent) for u in unit.combined_units.all()), ZERO
            )
            potential += rent
            since = unit.last_move_out
            rows.append({
                "id": unit.id,
                "building": unit.building.name,
                "label": unit.space_label,
                "floor": unit.floor,
                "unit_type": unit.get_unit_type_display(),
                "classification": unit.get_classification_display(),
                "monthly_rent": _f(rent),
                "status": unit.get_status_display(),
                "vacant_since": since.isoformat() if since else None,
                "days_vacant": (today - since).days if since and since <= today else None,
            })
        return Response({
            "building": _building_meta(building_id),
            "count": len(rows),
            "potential_rent": _f(potential),
            "units": rows,
        })


def _statement_rows(ledger, tenant_name=None):
    """Rent-roll rows reshaped for a statement table."""
    rows = []
    for row in ledger:
        charged = (
            Decimal(row["rent"]) + Decimal(row["vat"])
            + Decimal(row["other_charges"]) + Decimal(row["refunds"])
        )
        credits = Decimal(row["waived"]) + Decimal(row["credits"])
        balance = Decimal(row["balance"])
        paid = Decimal(row["paid"])
        if balance < 0:
            status = "In credit"
        elif balance == 0:
            status = "Paid"
        elif paid > 0 or credits > 0:
            status = "Partial"
        else:
            status = "Unpaid"
        entry = {
            "key": row["period_year"] * 12 + row["period_month"] - 1,
            "period": row["label"],
            "brought_forward": _f(row["brought_forward"]),
            "rent": _f(Decimal(row["rent"]) + Decimal(row["vat"])),
            "other_charges": _f(Decimal(row["other_charges"]) + Decimal(row["refunds"])),
            "expected": _f(charged),
            "paid": _f(paid),
            "credits": _f(credits),
            "balance": _f(balance),
            "status": status,
            "is_opening": row["is_opening"],
        }
        if tenant_name is not None:
            entry["tenant"] = tenant_name
        rows.append(entry)
    return rows


def _in_range(rows, start_key, end_key):
    return [
        r for r in rows
        if (start_key is None or r["key"] >= start_key)
        and (end_key is None or r["key"] <= end_key)
    ]


def _totals(rows) -> dict:
    """Opening, movements and closing for a run of consecutive statement rows."""
    if not rows:
        return {
            "opening_balance": 0.0, "total_expected": 0.0, "total_paid": 0.0,
            "total_credits": 0.0, "closing_balance": 0.0,
        }
    return {
        "opening_balance": rows[0]["brought_forward"],
        "total_expected": _f(sum((Decimal(str(r["expected"])) for r in rows), ZERO)),
        "total_paid": _f(sum((Decimal(str(r["paid"])) for r in rows), ZERO)),
        "total_credits": _f(sum((Decimal(str(r["credits"])) for r in rows), ZERO)),
        "closing_balance": rows[-1]["balance"],
    }


class TenantStatementReportView(APIView):
    """GET /api/reports/tenant-statement/<tenant_id>/?from=YYYY-MM&to=YYYY-MM

    The tenant's whole rent roll, month by month — the same roll-forward the
    statement PDF prints. ``from``/``to`` narrow the months shown; the opening
    balance is still what was brought into the first month shown, so the
    totals always reconcile::

        opening_balance + total_expected − total_paid − total_credits
            = closing_balance
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, tenant_id):
        tenant = get_object_or_404(
            Tenant.objects.select_related("unit", "unit__building"), pk=tenant_id
        )
        start_key, end_key = _period_range(request)
        ledger = build_monthly_ledger(tenant, months=0, today=_today())
        rows = _in_range(_statement_rows(ledger), start_key, end_key)
        totals = _totals(rows)
        return Response({
            "tenant": {
                "id": tenant.id,
                "name": tenant.full_name,
                "unit": _unit_name(tenant.unit),
                "phone": tenant.phone,
                "monthly_rent": _f(tenant.monthly_rent),
                "status": tenant.get_status_display(),
                "move_in_date": tenant.move_in_date.isoformat(),
                "move_out_date": (
                    tenant.move_out_date.isoformat() if tenant.move_out_date else None
                ),
            },
            **totals,
            # The old name for the closing balance, kept for older clients.
            "total_arrears": max(totals["closing_balance"], 0.0),
            "rows": rows,
        })


class UnitStatementReportView(APIView):
    """GET /api/reports/unit-statement/<unit_id>/?from=YYYY-MM&to=YYYY-MM

    Every tenancy the unit has had, each tenant's rent roll in turn, newest
    tenancy first. A unit folded into a combined space is reported through its
    head, where the tenancy is held.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, unit_id):
        unit = get_object_or_404(
            Unit.objects.select_related("building", "combined_into"), pk=unit_id
        )
        head = unit.combined_into or unit
        start_key, end_key = _period_range(request)
        today = _today()

        tenancies = []
        all_rows = []
        for tenant in head.tenants.order_by("-move_in_date", "-id"):
            ledger = build_monthly_ledger(tenant, months=0, today=today)
            rows = _in_range(_statement_rows(ledger, tenant.full_name), start_key, end_key)
            if not rows:
                continue
            tenancies.append({
                "tenant_id": tenant.id,
                "tenant": tenant.full_name,
                "status": tenant.get_status_display(),
                "move_in_date": tenant.move_in_date.isoformat(),
                "move_out_date": (
                    tenant.move_out_date.isoformat() if tenant.move_out_date else None
                ),
                **_totals(rows),
            })
            all_rows.extend(rows)

        return Response({
            "unit": {
                "id": head.id,
                "label": head.space_label,
                "building": head.building.name,
                "classification": head.get_classification_display(),
                "monthly_rent": _f(head.monthly_rent),
                "status": head.get_status_display(),
            },
            "tenancies": tenancies,
            "total_expected": _f(sum((Decimal(str(t["total_expected"])) for t in tenancies), ZERO)),
            "total_paid": _f(sum((Decimal(str(t["total_paid"])) for t in tenancies), ZERO)),
            "closing_balance": _f(sum((Decimal(str(t["closing_balance"])) for t in tenancies), ZERO)),
            "rows": all_rows,
        })


class LandlordStatementReportView(APIView):
    """GET /api/reports/landlord-statement/?month=&year=&building=

    The month on one page for the owner: income line by line, expenses by
    category, and what is left. Income and expenses are the P&L's figures to
    the shilling (``report_data.income_lines`` / ``expense_by_category``), so
    ``net`` is the P&L's net profit.

    Money that came in but is not the landlord's income is shown below the
    line and kept out of the totals: VAT on commercial rent is owed to KRA and
    deposits are held for the tenant.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        month, year = period_params(request, _today())
        building_id = building_param(request)

        lines = income_lines(month, year, building_id=building_id)
        categories = expense_by_category(month, year, building_id=building_id)
        total_expenses = sum((c["total"] for c in categories), ZERO)

        rows = []

        def add(section, description, amount):
            rows.append({"section": section, "description": description, "amount": _f(amount)})

        income_items = [
            ("Residential rent", lines["residential_rent"]),
            ("Commercial rent (excl. VAT)", lines["commercial_rent"]),
            ("Late fees", lines["late_fees"]),
            ("Other income", lines["other_income"]),
            *lines["manual_income"],
            ("Credits and refunds to tenants", lines["credit_adjustment"]),
        ]
        for description, amount in income_items:
            if amount:
                add("income", description, amount)
        for c in categories:
            add("expense", c["category"], c["total"])
        if lines["vat_collected"]:
            add("memo", "VAT collected on commercial rent (owed to KRA)", lines["vat_collected"])
        if lines["deposits_received"]:
            add("memo", "Security deposits received (held for tenants)", lines["deposits_received"])

        # Occupancy at a glance, for the same property scope.
        units = Unit.objects.filter(
            combined_into__isnull=True, building__property_type=PropertyType.RENTAL
        )
        if building_id:
            units = units.filter(building_id=building_id)
        occupied = units.exclude(
            status__in=(UnitStatus.VACANT, UnitStatus.UNDER_MAINTENANCE)
        ).count()

        return Response({
            "period": f"{month}/{year}",
            "building": _building_meta(building_id),
            "total_income": _f(lines["total"]),
            "total_expenses": _f(total_expenses),
            "net": _f(lines["total"] - total_expenses),
            "vat_collected": _f(lines["vat_collected"]),
            "deposits_received": _f(lines["deposits_received"]),
            "units_total": units.count(),
            "units_occupied": occupied,
            "rows": rows,
        })


__all__ = [
    "ExpiringLeasesReportView",
    "LandlordStatementReportView",
    "RentBalancesReportView",
    "RentOverpaymentsReportView",
    "TenantStatementReportView",
    "UnitStatementReportView",
    "VacantUnitsReportView",
]
