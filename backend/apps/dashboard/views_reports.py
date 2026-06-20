"""Dashboard views_reports — all reporting endpoints."""
from collections import defaultdict
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.buildings.models import Building, Unit, UnitStatus
from apps.expenses.models import Account, AccountType, Expense
from apps.payments.models import Arrears, Payment
from apps.tenants.models import Tenant


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
    """GET /api/reports/trial-balance/?month=4&year=2026

    Sourced from JournalLine so total_debit == total_credit exactly.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.ledger.models import JournalLine

        now = timezone.now()
        month = int(request.query_params.get("month", now.month))
        year = int(request.query_params.get("year", now.year))
        building_id = request.query_params.get("building")

        lines_qs = JournalLine.objects.filter(
            entry__period_month=month,
            entry__period_year=year,
            entry__is_posted=True,
        ).values(
            "account__code", "account__name"
        ).annotate(
            total_debit=Sum("debit"),
            total_credit=Sum("credit"),
        ).order_by("account__code")

        if building_id:
            lines_qs = lines_qs.filter(entry__building_id=building_id)

        accounts = []
        total_debit = Decimal("0")
        total_credit = Decimal("0")

        for row in lines_qs:
            dr = row["total_debit"] or Decimal("0")
            cr = row["total_credit"] or Decimal("0")
            total_debit += dr
            total_credit += cr
            accounts.append({
                "account": f"{row['account__code']} {row['account__name']}",
                "debit": float(dr),
                "credit": float(cr),
            })

        is_balanced = abs(total_debit - total_credit) < Decimal("0.01")

        return Response({
            "period": f"{month}/{year}",
            "building": int(building_id) if building_id else None,
            "accounts": accounts,
            "total_debit": float(round(total_debit, 2)),
            "total_credit": float(round(total_credit, 2)),
            "is_balanced": is_balanced,
        })


class AccountingDashboardView(APIView):
    """GET /api/reports/accounting/?tab=coa|pnl|balance_sheet|ledger|petty_cash|budgeting&month=&year=

    Drives the Accounting Suite tabs on ExpensesPage. Each tab returns the shape
    that its frontend view expects (see ExpensesPage CoAView, PnLView, etc.).

    Built around the Wilkem Ventures Rentals & Commercials Chart of Accounts.
    All financial data is sourced from the JournalLine general ledger.
    """
    permission_classes = [IsAuthenticated]

    VALID_TABS = {"coa", "pnl", "balance_sheet", "ledger", "petty_cash", "budgeting"}

    DEBIT_NORMAL_TYPES = {AccountType.ASSET, AccountType.EXPENSE}
    CREDIT_NORMAL_TYPES = {AccountType.LIABILITY, AccountType.EQUITY, AccountType.INCOME}

    def get(self, request):
        tab = request.query_params.get("tab", "coa")
        if tab not in self.VALID_TABS:
            return Response({"detail": f"Unknown tab '{tab}'."}, status=400)

        now = timezone.now()
        month = int(request.query_params.get("month", now.month))
        year = int(request.query_params.get("year", now.year))

        handler = getattr(self, f"_tab_{tab}")
        return Response(handler(month, year))

    # ── helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _ledger_balances_for_period(month: int, year: int) -> dict:
        """
        Return {account_code: (debit_sum, credit_sum)} for the given period.
        Used by CoA and P&L tabs.
        """
        from apps.ledger.models import JournalLine
        rows = (
            JournalLine.objects.filter(
                entry__period_month=month,
                entry__period_year=year,
                entry__is_posted=True,
            )
            .values("account__code", "account__account_type")
            .annotate(total_debit=Sum("debit"), total_credit=Sum("credit"))
        )
        result = {}
        for r in rows:
            result[r["account__code"]] = (
                r["total_debit"] or Decimal("0"),
                r["total_credit"] or Decimal("0"),
            )
        return result

    @staticmethod
    def _ledger_balances_cumulative(month: int, year: int) -> dict:
        """
        Return {account_code: (debit_sum, credit_sum)} cumulative through end of period.
        Used by Balance Sheet.
        """
        from apps.ledger.models import JournalLine
        period_filter = (
            Q(entry__period_year__lt=year)
            | Q(entry__period_year=year, entry__period_month__lte=month)
        )
        rows = (
            JournalLine.objects.filter(period_filter, entry__is_posted=True)
            .values("account__code", "account__account_type")
            .annotate(total_debit=Sum("debit"), total_credit=Sum("credit"))
        )
        result = {}
        for r in rows:
            result[r["account__code"]] = (
                r["total_debit"] or Decimal("0"),
                r["total_credit"] or Decimal("0"),
            )
        return result

    @classmethod
    def _net_balance(cls, account_type: str, debit: Decimal, credit: Decimal) -> Decimal:
        """Return the signed net balance respecting normal balance side."""
        if account_type in (AccountType.ASSET, AccountType.EXPENSE):
            return debit - credit
        return credit - debit

    # ── Chart of Accounts ──────────────────────────────────────────────────
    def _tab_coa(self, month: int, year: int):
        """List all GL accounts with in-period balances from the ledger."""
        period_balances = self._ledger_balances_for_period(month, year)
        accounts = []
        for acct in Account.objects.filter(is_active=True).order_by("code"):
            if acct.is_header:
                balance = None
            else:
                dr, cr = period_balances.get(acct.code, (Decimal("0"), Decimal("0")))
                balance = float(self._net_balance(acct.account_type, dr, cr))
            accounts.append({
                "code": acct.code,
                "name": acct.name,
                "type": acct.get_account_type_display(),
                "parent_code": acct.parent_code,
                "is_header": acct.is_header,
                "balance": balance,
            })
        return {"period": f"{month}/{year}", "accounts": accounts}

    # ── Profit & Loss ──────────────────────────────────────────────────────
    def _tab_pnl(self, month: int, year: int):
        """4110/4120/4200 income minus 5xxx-6xxx expense, sourced from ledger."""
        period_balances = self._ledger_balances_for_period(month, year)

        def income(code):
            dr, cr = period_balances.get(code, (Decimal("0"), Decimal("0")))
            return cr - dr  # credit-normal

        def expense_amount(code):
            dr, cr = period_balances.get(code, (Decimal("0"), Decimal("0")))
            return dr - cr  # debit-normal

        residential_income = income("4110")
        commercial_income = income("4120")
        rental_income = residential_income + commercial_income
        late_fees = income("4200")
        other_income = income("4150") + income("4250")
        total_income = rental_income + late_fees + other_income

        # Expense breakdown — group by GL account for all 5xxx/6xxx
        expense_rows = []
        total_expenses = Decimal("0")
        for acct in Account.objects.filter(
            is_active=True, is_header=False,
            account_type=AccountType.EXPENSE
        ).order_by("code"):
            amt = expense_amount(acct.code)
            if amt == Decimal("0"):
                continue
            total_expenses += amt
            expense_rows.append({
                "category": f"{acct.code} — {acct.name}",
                "amount": float(amt),
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

    # ── Balance Sheet ──────────────────────────────────────────────────────
    def _tab_balance_sheet(self, month: int, year: int):
        """
        Balance sheet sourced from cumulative ledger balances.
        Equity = 3100 + 3300 + retained earnings (cumulative income − expense).
        Assets == Liabilities + Equity is asserted.
        """
        balances = self._ledger_balances_cumulative(month, year)

        def asset(code):
            dr, cr = balances.get(code, (Decimal("0"), Decimal("0")))
            return dr - cr

        def liability(code):
            dr, cr = balances.get(code, (Decimal("0"), Decimal("0")))
            return cr - dr

        def equity_acct(code):
            dr, cr = balances.get(code, (Decimal("0"), Decimal("0")))
            return cr - dr

        def income_acct(code):
            dr, cr = balances.get(code, (Decimal("0"), Decimal("0")))
            return cr - dr

        def expense_acct(code):
            dr, cr = balances.get(code, (Decimal("0"), Decimal("0")))
            return dr - cr

        assets = {
            "1010 Petty Cash":                            float(asset("1010")),
            "1020 Operating Bank Account":                float(asset("1020")),
            "1030 Tenant Security Deposit Bank Account":  float(asset("1030")),
            "1040 Accounts Receivable (Rent Arrears)":    float(asset("1040")),
            "1060 Investment Property / Land":            float(asset("1060")),
            "1350 Buildings & Improvements":              float(asset("1350")),
        }

        liabilities = {
            "2100 Tenant Security Deposits Held": float(liability("2100")),
            "2500 Mortgages Payable / Bank Loans": float(liability("2500")),
        }

        # Retained earnings = cumulative income accounts − cumulative expense accounts
        all_income_codes = list(
            Account.objects.filter(is_active=True, is_header=False, account_type=AccountType.INCOME)
            .values_list("code", flat=True)
        )
        all_expense_codes = list(
            Account.objects.filter(is_active=True, is_header=False, account_type=AccountType.EXPENSE)
            .values_list("code", flat=True)
        )
        cumulative_income = sum(income_acct(c) for c in all_income_codes)
        cumulative_expenses = sum(expense_acct(c) for c in all_expense_codes)
        retained_earnings = cumulative_income - cumulative_expenses

        owner_equity = equity_acct("3100") + equity_acct("3300")
        total_equity = owner_equity + retained_earnings

        total_assets = sum(assets.values())
        total_liabilities = sum(liabilities.values())
        balanced = abs(total_assets - (total_liabilities + float(total_equity))) < 0.01

        return {
            "period": f"{month}/{year}",
            "assets": assets,
            "liabilities": liabilities,
            "equity": float(total_equity),
            "equity_detail": {
                "owner_equity": float(owner_equity),
                "retained_earnings": float(retained_earnings),
            },
            "balanced": balanced,
        }

    # ── General Ledger ─────────────────────────────────────────────────────
    def _tab_ledger(self, month: int, year: int):
        """
        Return real journal entries for the period.
        Supports optional ?account=<code> filter for single-account ledger view.
        """
        from apps.ledger.models import JournalEntry

        entries_qs = (
            JournalEntry.objects.filter(
                period_month=month,
                period_year=year,
                is_posted=True,
            )
            .prefetch_related("lines", "lines__account")
            .order_by("date", "id")
        )

        entries = []
        for entry in entries_qs:
            lines = []
            for line in entry.lines.all():
                lines.append({
                    "account_code": line.account.code,
                    "account_name": line.account.name,
                    "debit": float(line.debit),
                    "credit": float(line.credit),
                    "description": line.description,
                })
            entries.append({
                "id": entry.pk,
                "date": entry.date.isoformat(),
                "memo": entry.memo,
                "reference": entry.reference,
                "kind": entry.kind,
                "lines": lines,
            })

        return {
            "period": f"{month}/{year}",
            "entries": entries,
        }

    # ── Petty Cash ─────────────────────────────────────────────────────────
    def _tab_petty_cash(self, month: int, year: int):
        """
        Show 1010 Petty Cash lines for the period.
        closing_balance = cumulative balance of account 1010.
        """
        from apps.ledger.models import JournalLine

        # Period entries for 1010
        period_lines = (
            JournalLine.objects.filter(
                account__code="1010",
                entry__period_month=month,
                entry__period_year=year,
                entry__is_posted=True,
            )
            .select_related("entry")
            .order_by("entry__date", "entry__id")
        )

        entries = []
        for line in period_lines:
            entries.append({
                "date": line.entry.date.isoformat(),
                "memo": line.entry.memo,
                "debit": float(line.debit),
                "credit": float(line.credit),
                "description": line.description,
            })

        # Cumulative closing balance for 1010 (debit-normal asset)
        cum_filter = (
            Q(entry__period_year__lt=year)
            | Q(entry__period_year=year, entry__period_month__lte=month)
        )
        agg = JournalLine.objects.filter(
            cum_filter, account__code="1010", entry__is_posted=True
        ).aggregate(total_debit=Sum("debit"), total_credit=Sum("credit"))
        closing_balance = (agg["total_debit"] or Decimal("0")) - (agg["total_credit"] or Decimal("0"))

        return {
            "period": f"{month}/{year}",
            "entries": entries,
            "closing_balance": float(closing_balance),
        }

    # ── Budgeting ──────────────────────────────────────────────────────────
    def _tab_budgeting(self, month: int, year: int):
        """
        Per-account budgeted vs actual (ledger balance), with totals.
        Falls back to portfolio rent estimate if no budgets are defined.
        """
        from apps.ledger.models import Budget

        period_balances = self._ledger_balances_for_period(month, year)
        budgets = Budget.objects.filter(
            period_month=month, period_year=year
        ).select_related("account")

        rows = []
        total_budgeted = Decimal("0")
        total_actual = Decimal("0")

        if budgets.exists():
            for b in budgets.order_by("account__code"):
                dr, cr = period_balances.get(b.account.code, (Decimal("0"), Decimal("0")))
                actual = self._net_balance(b.account.account_type, dr, cr)
                variance = actual - b.amount
                rows.append({
                    "category": f"{b.account.code} — {b.account.name}",
                    "budgeted": float(b.amount),
                    "actual": float(actual),
                    "variance": float(variance),
                })
                total_budgeted += b.amount
                total_actual += actual
        else:
            # Fallback: compare actual rent collected vs expected from tenants
            from apps.tenants.models import TenantStatus
            actual_rent_dr, actual_rent_cr = period_balances.get("4110", (Decimal("0"), Decimal("0")))
            actual_rent_dr2, actual_rent_cr2 = period_balances.get("4120", (Decimal("0"), Decimal("0")))
            actual_rent = (actual_rent_cr - actual_rent_dr) + (actual_rent_cr2 - actual_rent_dr2)
            expected = (
                Tenant.objects.filter(status=TenantStatus.ACTIVE)
                .aggregate(t=Sum("monthly_rent"))["t"] or Decimal("0")
            )
            variance = actual_rent - expected
            rows.append({
                "category": "Rent (portfolio)",
                "budgeted": float(expected),
                "actual": float(actual_rent),
                "variance": float(variance),
            })
            total_budgeted = expected
            total_actual = actual_rent

        return {
            "period": f"{month}/{year}",
            "rows": rows,
            "total_budgeted": float(total_budgeted),
            "total_actual": float(total_actual),
            "total_variance": float(total_actual - total_budgeted),
        }

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
