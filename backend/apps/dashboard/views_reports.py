"""Dashboard views_reports — all reporting endpoints."""
from collections import defaultdict
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.expenses.models import Account, AccountType, Expense
from apps.payments.models import Arrears, Payment, PaymentType
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


class AccountingDashboardView(APIView):
    """GET /api/reports/accounting/?tab=coa|pnl|balance_sheet|ledger|petty_cash|budgeting&month=&year=

    Drives the Accounting Suite tabs on ExpensesPage. Each tab returns the shape
    that its frontend view expects (see ExpensesPage CoAView, PnLView, etc.).

    Built around the Wilkem Ventures Rentals & Commercials Chart of Accounts:
      Assets 1010-1370, Liabilities 2010-2800, Equity 3100-3300,
      Income 4110-4250, Operating Expenses 5100-5940,
      Fixed/Non-operating 6100-6600.
    """
    permission_classes = [IsAuthenticated]

    VALID_TABS = {"coa", "pnl", "balance_sheet", "ledger", "petty_cash", "budgeting"}

    def get(self, request):
        tab = request.query_params.get("tab", "coa")
        if tab not in self.VALID_TABS:
            return Response({"detail": f"Unknown tab '{tab}'."}, status=400)

        now = timezone.now()
        month = int(request.query_params.get("month", now.month))
        year = int(request.query_params.get("year", now.year))

        handler = getattr(self, f"_tab_{tab}")
        return Response(handler(month, year))

    # ── Chart of Accounts ──────────────────────────────────────────────────
    def _tab_coa(self, month: int, year: int):
        """List all GL accounts with the in-period balance where it can be computed."""
        income_by_type = self._income_by_payment_type(month, year)
        rent_by_class = self._rent_income_by_classification(month, year)
        expense_by_account = self._expense_by_account(month, year)
        accounts = []
        for acct in Account.objects.filter(is_active=True).order_by("code"):
            balance = self._account_balance(acct, income_by_type, rent_by_class, expense_by_account)
            accounts.append({
                "code": acct.code,
                "name": acct.name,
                "type": acct.get_account_type_display(),
                "parent_code": acct.parent_code,
                "is_header": acct.is_header,
                "balance": None if acct.is_header else float(balance),
            })
        return {"period": f"{month}/{year}", "accounts": accounts}

    # ── Profit & Loss ──────────────────────────────────────────────────────
    def _tab_pnl(self, month: int, year: int):
        """4110/4120/4200 income minus 5xxx-6xxx expense, with a per-account breakdown."""
        income_by_type = self._income_by_payment_type(month, year)
        rent_by_class = self._rent_income_by_classification(month, year)
        residential_income = rent_by_class.get(UnitClassification.RESIDENTIAL, Decimal("0"))
        commercial_income = rent_by_class.get(UnitClassification.BUSINESS, Decimal("0"))
        rental_income = residential_income + commercial_income
        late_fees = income_by_type.get(PaymentType.LATE_FEE, Decimal("0"))
        other_income = income_by_type.get(PaymentType.OTHER, Decimal("0"))
        total_income = rental_income + late_fees + other_income

        expense_rows = []
        total_expenses = Decimal("0")
        for row in (
            Expense.objects.filter(period_month=month, period_year=year)
            .values("category__name", "category__account__code", "category__account__name")
            .annotate(total=Sum("amount"))
            .order_by("category__account__code", "category__name")
        ):
            amount = row["total"] or Decimal("0")
            total_expenses += amount
            label = row["category__account__name"] or row["category__name"]
            code = row["category__account__code"]
            expense_rows.append({
                "category": f"{code} — {label}" if code else label,
                "amount": float(amount),
            })

        return {
            "period": f"{month}/{year}",
            "income": float(total_income),
            "rental_income": float(rental_income),
            "residential_income": float(residential_income),
            "commercial_income": float(commercial_income),
            "late_fees": float(late_fees),
            "other_income": float(other_income),
            "total_expenses": float(total_expenses),
            "net_profit": float(total_income - total_expenses),
            "expense_breakdown": expense_rows,
        }

    # ── Balance Sheet (best-effort with current models) ────────────────────
    def _tab_balance_sheet(self, month: int, year: int):
        """Snapshot up to the end of the requested period.

        We have no GL postings for fixed assets, mortgage, or owner equity yet,
        so 1060/1350/2500/3100-3300 stay at zero. Cash, A/R, and deposits-held
        are derived from Payments/Arrears/Tenants.
        """
        period_filter = Q(period_year__lt=year) | Q(period_year=year, period_month__lte=month)

        rent_collected = (
            Payment.objects.filter(period_filter, payment_type=PaymentType.RENT)
            .aggregate(t=Sum("amount"))["t"] or Decimal("0")
        )
        late_fee_collected = (
            Payment.objects.filter(period_filter, payment_type=PaymentType.LATE_FEE)
            .aggregate(t=Sum("amount"))["t"] or Decimal("0")
        )
        deposits_collected = (
            Payment.objects.filter(period_filter, payment_type=PaymentType.DEPOSIT)
            .aggregate(t=Sum("amount"))["t"] or Decimal("0")
        )
        accounts_receivable = (
            Arrears.objects.filter(period_filter, is_cleared=False)
            .aggregate(t=Sum("balance"))["t"] or Decimal("0")
        )
        # Deposits liability uses Tenant.deposit_paid for active tenants (the
        # current "held" balance), since we don't yet track refunds as journal
        # entries. Falls back to payment-typed deposits if no tenants exist.
        deposit_liability = (
            Tenant.objects.filter(status=TenantStatus.ACTIVE)
            .aggregate(t=Sum("deposit_paid"))["t"] or deposits_collected
        )
        expenses_paid = (
            Expense.objects.filter(period_filter)
            .aggregate(t=Sum("amount"))["t"] or Decimal("0")
        )

        operating_cash = rent_collected + late_fee_collected - expenses_paid

        assets = {
            "1020 Operating Bank Account":              float(operating_cash),
            "1030 Tenant Security Deposit Bank Account": float(deposits_collected),
            "1040 Accounts Receivable (Rent Arrears)":   float(accounts_receivable),
            "1060 Investment Property / Land":           0.0,
            "1350 Buildings & Improvements":             0.0,
        }
        liabilities = {
            "2100 Tenant Security Deposits Held": float(deposit_liability),
            "2500 Mortgages Payable / Bank Loans": 0.0,
        }
        # Equity plugged so the sheet balances; flagged so the UI can show a note.
        total_assets = sum(assets.values())
        total_liabilities = sum(liabilities.values())
        equity = total_assets - total_liabilities

        return {
            "period": f"{month}/{year}",
            "assets": assets,
            "liabilities": liabilities,
            "equity": float(equity),
            "note": (
                "Fixed assets, mortgage principal, and owner equity are not "
                "yet tracked as journal entries — equity is shown as the "
                "plug figure (assets − liabilities)."
            ),
        }

    # ── General Ledger (placeholder — needs double-entry to be meaningful) ─
    def _tab_ledger(self, month: int, year: int):
        return {
            "period": f"{month}/{year}",
            "entries": [],
            "note": (
                "General ledger detail requires double-entry journal entries, "
                "which are not yet implemented. Use the Chart of Accounts and "
                "P&L tabs to see per-account totals."
            ),
        }

    # ── Petty Cash (placeholder — no petty cash model yet) ─────────────────
    def _tab_petty_cash(self, month: int, year: int):
        return {
            "period": f"{month}/{year}",
            "entries": [],
            "closing_balance": 0,
            "note": "Petty cash is not tracked separately yet.",
        }

    # ── Budgeting (placeholder — no budget model yet) ──────────────────────
    def _tab_budgeting(self, month: int, year: int):
        actual = (
            Payment.objects.filter(period_month=month, period_year=year, payment_type=PaymentType.RENT)
            .aggregate(t=Sum("amount"))["t"] or Decimal("0")
        )
        expected = (
            Tenant.objects.filter(status=TenantStatus.ACTIVE)
            .aggregate(t=Sum("monthly_rent"))["t"] or Decimal("0")
        )
        variance = actual - expected
        return {
            "period": f"{month}/{year}",
            "rows": [
                {
                    "category": "Rent (portfolio)",
                    "budgeted": float(expected),
                    "actual": float(actual),
                    "variance": float(variance),
                },
            ],
            "total_budgeted": float(expected),
            "total_actual": float(actual),
            "total_variance": float(variance),
            "note": (
                "Budgeted income is derived from the sum of active tenants' "
                "monthly rent. Per-category budgets aren't tracked yet."
            ),
        }

    # ── helpers ────────────────────────────────────────────────────────────
    @staticmethod
    def _income_by_payment_type(month: int, year: int) -> dict:
        rows = (
            Payment.objects.filter(period_month=month, period_year=year)
            .values("payment_type")
            .annotate(total=Sum("amount"))
        )
        return {r["payment_type"]: r["total"] or Decimal("0") for r in rows}

    @staticmethod
    def _rent_income_by_classification(month: int, year: int) -> dict:
        """Split rent collected into residential vs commercial by the unit's classification."""
        rows = (
            Payment.objects.filter(period_month=month, period_year=year, payment_type=PaymentType.RENT)
            .values("tenant__unit__classification")
            .annotate(total=Sum("amount"))
        )
        return {r["tenant__unit__classification"]: r["total"] or Decimal("0") for r in rows}

    @staticmethod
    def _expense_by_account(month: int, year: int) -> dict:
        rows = (
            Expense.objects.filter(period_month=month, period_year=year)
            .values("category__account__code")
            .annotate(total=Sum("amount"))
        )
        return {r["category__account__code"]: r["total"] or Decimal("0") for r in rows if r["category__account__code"]}

    @staticmethod
    def _account_balance(acct, income_by_type, rent_by_class, expense_by_account) -> Decimal:
        """Best-effort in-period balance per account using existing data."""
        if acct.account_type == AccountType.INCOME:
            # Rent is split by the unit's classification (residential vs commercial).
            if acct.code == "4110":
                return rent_by_class.get(UnitClassification.RESIDENTIAL, Decimal("0"))
            if acct.code == "4120":
                return rent_by_class.get(UnitClassification.BUSINESS, Decimal("0"))
            if acct.code == "4200":
                return income_by_type.get(PaymentType.LATE_FEE, Decimal("0"))
            return Decimal("0")
        if acct.account_type == AccountType.EXPENSE:
            return expense_by_account.get(acct.code, Decimal("0"))
        # Assets, liabilities, equity — not yet GL-tracked.
        return Decimal("0")


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
