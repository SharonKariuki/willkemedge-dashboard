"""The Accounting page's API: statements read from the general ledger.

GET /api/reports/accounting/?tab=<tab>&start=YYYY-MM-DD&end=YYYY-MM-DD
    tab        balance_sheet | pnl | trial_balance | ledger | coa | petty_cash | budgeting
    start/end  the period, both days inclusive (default: this month). The older
               ``month``/``year`` pair still works and means that whole month.
    building   one property's books
    export     csv | xlsx | pdf — download exactly what the tab shows

General ledger only:
    view       account (default; opening, lines, running balance, closing per
               account) | journal (entries with their balanced lines)
    account    account codes, comma-separated
    source     what posted the entry (payment, expense, utility_charge, …), comma-separated
    q          search memo, reference and line description

Trial balance only:
    mode       balances (closing balances at ``end``; default) | movements (debits
               and credits posted in the period)

POST /api/reports/export/  — any report table the browser already holds, as a
    CSV, Excel or PDF file. See ``ReportExportView``.
"""
from __future__ import annotations

import calendar
import datetime as _dt
from decimal import Decimal

from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.buildings.models import Building
from apps.ledger import reports as gl

from .exports import FORMATS, Column, Sheet, export_format, file_response
from .report_data import building_param, int_param

MAX_RANGE_DAYS = 366 * 10


def _jsonable(value):
    """Decimals to floats and dates to ISO strings, all the way down."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (_dt.date, _dt.datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def period_range(request) -> tuple[_dt.date, _dt.date]:
    """``start``/``end`` dates; or a ``month``/``year``; or this month."""
    raw_start, raw_end = request.query_params.get("start"), request.query_params.get("end")
    if raw_start or raw_end:
        start = parse_date(raw_start or "")
        end = parse_date(raw_end or "")
        if start is None:
            raise ValidationError({"start": "Give a start date as YYYY-MM-DD."})
        if end is None:
            raise ValidationError({"end": "Give an end date as YYYY-MM-DD."})
    else:
        today = timezone.localdate()
        month = int_param(request, "month", today.month, lo=1, hi=12)
        year = int_param(request, "year", today.year, lo=2000, hi=2100)
        start = _dt.date(year, month, 1)
        end = _dt.date(year, month, calendar.monthrange(year, month)[1])
    if end < start:
        raise ValidationError({"end": "The end date is before the start date."})
    if (end - start).days > MAX_RANGE_DAYS:
        raise ValidationError({"start": "Choose a period of ten years or less."})
    return start, end


def _csv_list(request, name) -> list[str]:
    raw = request.query_params.get(name) or ""
    return [part.strip() for part in raw.split(",") if part.strip()]


def _fmt_day(day: _dt.date) -> str:
    return day.strftime("%d %b %Y")


class AccountingDashboardView(APIView):
    permission_classes = [IsAuthenticated]

    TABS = ("balance_sheet", "pnl", "trial_balance", "ledger", "coa", "petty_cash", "budgeting")

    def get(self, request):
        tab = request.query_params.get("tab", "balance_sheet")
        if tab not in self.TABS:
            return Response({"detail": f"Unknown tab '{tab}'."}, status=400)
        start, end = period_range(request)
        building_id = building_param(request)
        building = None
        if building_id:
            building = Building.objects.filter(pk=building_id).only("id", "name").first()
            if building is None:
                raise ValidationError({"building": "No such building."})
        fmt = export_format(request)

        self.start, self.end, self.building_id = start, end, building_id
        self.scope = building.name if building else "All properties"
        data, sheet = getattr(self, f"_tab_{tab}")(request)

        if fmt:
            return file_response(sheet, fmt, f"{sheet.title} {start} to {end}")
        return Response(_jsonable({
            "tab": tab,
            "start": start,
            "end": end,
            "building": {"id": building.id, "name": building.name} if building else None,
            "period": f"{_fmt_day(start)} – {_fmt_day(end)}",
            **data,
        }))

    # ── helpers ─────────────────────────────────────────────────────────────
    def _subtitle(self, *extra, as_at=False) -> list[str]:
        period = (
            f"As at {_fmt_day(self.end)}" if as_at
            else f"Period: {_fmt_day(self.start)} to {_fmt_day(self.end)}"
        )
        return [period, f"Property: {self.scope}", *[e for e in extra if e]]

    # ── Balance sheet ───────────────────────────────────────────────────────
    def _tab_balance_sheet(self, request):
        data = gl.balance_sheet(self.end, building_id=self.building_id)
        cols = [Column("code", "Code", width=8), Column("name", "Account", width=40),
                Column("amount", "Amount (KES)", "money", 16)]
        rows = []
        for title, groups, total in (
            ("Assets", data["assets"], data["total_assets"]),
            ("Liabilities", data["liabilities"], data["total_liabilities"]),
            ("Equity", data["equity"], data["total_equity"]),
        ):
            rows.append({"_style": "heading", "name": title.upper()})
            for g in groups:
                # A lone group named like its section ("Assets" under ASSETS)
                # would only repeat the section's own heading and total.
                own = len(groups) > 1 or g["name"].lower() != title.lower()
                if own:
                    rows.append({"_style": "heading", "code": g["code"], "name": g["name"]})
                rows += [{"code": a["code"], "name": a["name"], "amount": a["amount"]} for a in g["accounts"]]
                if own:
                    rows.append({"_style": "subtotal", "name": f"Total {g['name'].lower()}", "amount": g["total"]})
            rows.append({"_style": "total", "name": f"Total {title.lower()}", "amount": total})
        rows.append({"_style": "total", "name": "Total liabilities and equity",
                     "amount": data["total_liabilities_and_equity"]})
        notes = ["Balanced: assets equal liabilities plus equity." if data["balanced"]
                 else f"Out of balance by KES {data['difference']:,.2f}."]
        return data, Sheet("Balance Sheet", cols, rows, self._subtitle(as_at=True), notes)

    # ── Profit and loss ─────────────────────────────────────────────────────
    def _tab_pnl(self, request):
        data = gl.profit_and_loss(self.start, self.end, building_id=self.building_id)
        cols = [Column("code", "Code", width=8), Column("name", "Account", width=40),
                Column("amount", "Amount (KES)", "money", 16)]
        rows = []
        for title, groups, total in (("Income", data["income"], data["total_income"]),
                                     ("Expenses", data["expenses"], data["total_expenses"])):
            rows.append({"_style": "heading", "name": title.upper()})
            for g in groups:
                rows += [{"code": a["code"], "name": a["name"], "amount": a["amount"]} for a in g["accounts"]]
            rows.append({"_style": "total", "name": f"Total {title.lower()}", "amount": total})
        rows.append({"_style": "total", "name": "Net profit" if data["net_profit"] >= 0 else "Net loss",
                     "amount": data["net_profit"]})
        notes = ["From the general ledger: rent when received, water when billed, VAT excluded."]
        return data, Sheet("Profit and Loss", cols, rows, self._subtitle(), notes)

    # ── Trial balance ───────────────────────────────────────────────────────
    def _tab_trial_balance(self, request):
        mode = request.query_params.get("mode", "balances")
        if mode not in ("balances", "movements"):
            raise ValidationError({"mode": "Use balances or movements."})
        data = gl.trial_balance(self.start, self.end, building_id=self.building_id, mode=mode)
        cols = [Column("code", "Code", width=8), Column("name", "Account", width=36),
                Column("type", "Type", width=12), Column("debit", "Debit (KES)", "money", 16),
                Column("credit", "Credit (KES)", "money", 16)]
        rows = [dict(r) for r in data["rows"]]
        rows.append({"_style": "total", "name": "Total", "debit": data["total_debit"], "credit": data["total_credit"]})
        if mode == "movements":
            subtitle = self._subtitle("Debits and credits posted in the period")
        else:
            subtitle = self._subtitle("Closing balances; income and expenses for the year to date", as_at=True)
        notes = ["Balanced." if data["balanced"] else "Debits and credits do not agree."]
        return data, Sheet("Trial Balance", cols, rows, subtitle, notes)

    # ── General ledger ──────────────────────────────────────────────────────
    def _ledger_filters(self, request):
        accounts = _csv_list(request, "account")
        sources = _csv_list(request, "source")
        search = (request.query_params.get("q") or "").strip()
        described = []
        if accounts:
            described.append("Accounts: " + ", ".join(accounts))
        if sources:
            described.append("Source: " + ", ".join(gl.source_label(s) for s in sources))
        if search:
            described.append(f'Search: "{search}"')
        return accounts, sources, search, described

    def _account_ledger_sheet(self, title, data, subtitle):
        cols = [Column("date", "Date", "date", 11), Column("reference", "Reference", width=20),
                Column("description", "Description", width=36), Column("source", "Source", width=14),
                Column("debit", "Debit", "money", 13), Column("credit", "Credit", "money", 13),
                Column("balance", "Balance", "money", 14)]
        rows = []
        for acct in data["accounts"]:
            rows.append({"_style": "heading", "date": None,
                         "description": f"{acct['code']} {acct['name']}", "source": acct["type"]})
            rows.append({"_style": "opening", "description": "Opening balance", "balance": acct["opening"]})
            rows += [
                {"date": ln["date"], "reference": ln["reference"],
                 "description": f"{ln['description']} — {ln['detail']}" if ln["detail"] else ln["description"],
                 "source": ln["source"], "debit": ln["debit"] or None, "credit": ln["credit"] or None,
                 "balance": ln["balance"]}
                for ln in acct["lines"]
            ]
            rows.append({"_style": "closing", "description": f"Closing balance — {acct['code']}",
                         "debit": acct["debit"], "credit": acct["credit"], "balance": acct["closing"]})
        rows.append({"_style": "total", "description": "Total of lines shown",
                     "debit": data["total_debit"], "credit": data["total_credit"]})
        notes = ["Balances are on each account's normal side: debit for assets and expenses, "
                 "credit for liabilities, equity and income. Income and expense accounts open at "
                 "zero on 1 January."]
        if data["filtered"]:
            notes.append("Filtered view: running balances still count every line in the period.")
        return Sheet(title, cols, rows, subtitle, notes)

    def _tab_ledger(self, request):
        view = request.query_params.get("view", "account")
        if view not in ("account", "journal"):
            raise ValidationError({"view": "Use account or journal."})
        accounts, sources, search, described = self._ledger_filters(request)
        subtitle = self._subtitle(*described)

        if view == "journal":
            data = gl.journal(self.start, self.end, building_id=self.building_id,
                              sources=sources, search=search)
            cols = [Column("date", "Date", "date", 11), Column("entry", "Entry", "number", 7),
                    Column("reference", "Reference", width=20), Column("account", "Account", width=28),
                    Column("description", "Description", width=36),
                    Column("debit", "Debit", "money", 13), Column("credit", "Credit", "money", 13)]
            rows = []
            for e in data["entries"]:
                rows.append({"_style": "heading", "date": e["date"], "entry": e["id"],
                             "reference": e["reference"], "description": f"{e['memo']} ({e['source']})"})
                rows += [{"account": f"{ln['account_code']} {ln['account_name']}",
                          "description": ln["description"], "debit": ln["debit"] or None,
                          "credit": ln["credit"] or None} for ln in e["lines"]]
            rows.append({"_style": "total", "description": f"{len(data['entries'])} entries",
                         "debit": data["total"], "credit": data["total"]})
            return {"view": view, **data}, Sheet("Journal", cols, rows, subtitle)

        data = gl.general_ledger(self.start, self.end, building_id=self.building_id,
                                 account_codes=accounts, sources=sources, search=search)
        return {"view": view, **data}, self._account_ledger_sheet("General Ledger", data, subtitle)

    def _tab_petty_cash(self, request):
        data = gl.general_ledger(self.start, self.end, building_id=self.building_id, account_codes=["1010"])
        acct = data["accounts"][0] if data["accounts"] else None
        payload = {
            "opening": acct["opening"] if acct else Decimal("0"),
            "closing_balance": acct["closing"] if acct else Decimal("0"),
            "cash_in": acct["debit"] if acct else Decimal("0"),
            "cash_out": acct["credit"] if acct else Decimal("0"),
            "entries": acct["lines"] if acct else [],
        }
        return payload, self._account_ledger_sheet("Petty Cash", data, self._subtitle("Account 1010 Petty Cash"))

    # ── Chart of accounts ───────────────────────────────────────────────────
    def _tab_coa(self, request):
        data = gl.chart_of_accounts(self.start, self.end, building_id=self.building_id)
        cols = [Column("code", "Code", width=8), Column("name", "Account", width=36),
                Column("type", "Type", width=11), Column("opening", "Opening", "money", 14),
                Column("debit", "Debits", "money", 14), Column("credit", "Credits", "money", 14),
                Column("closing", "Closing", "money", 14)]
        rows = []
        for a in data["accounts"]:
            if a["is_header"]:
                rows.append({"_style": "heading", "code": a["code"], "name": a["name"], "closing": a["closing"]})
            else:
                rows.append({k: a.get(k) for k in ("code", "name", "type", "opening", "debit", "credit", "closing")})
        return data, Sheet("Chart of Accounts", cols, rows, self._subtitle())

    # ── Budget ──────────────────────────────────────────────────────────────
    def _tab_budgeting(self, request):
        data = gl.budget_vs_actual(self.start, self.end, building_id=self.building_id)
        cols = [Column("category", "Line", width=36), Column("budgeted", "Budgeted", "money", 15),
                Column("actual", "Actual", "money", 15), Column("variance", "Variance", "money", 15)]
        rows = [dict(r) for r in data["rows"]]
        rows.append({"_style": "total", "category": "Total", "budgeted": data["total_budgeted"],
                     "actual": data["total_actual"], "variance": data["total_variance"]})
        notes = ([] if data["basis"] == "budgets" else
                 ["No budget has been set for this period: rent received is compared with the monthly "
                  "rent of current tenants."])
        return data, Sheet("Budget vs Actual", cols, rows, self._subtitle(), notes)


class ReportExportView(APIView):
    """POST /api/reports/export/ — a report table the page already shows, as a file.

    Body::

        {"format": "xlsx", "title": "Rent Balances — September 2026",
         "subtitle": ["All buildings"], "notes": [],
         "columns": [{"key": "tenant", "label": "Tenant"},
                     {"key": "balance", "label": "Balance", "kind": "money"}],
         "rows": [{"tenant": "…", "balance": 1200.5}],
         "footer": {"tenant": "Total", "balance": 1200.5}}

    The Reports page sends the rows it is displaying, filters applied, so the
    Excel and PDF files match the screen exactly.
    """
    permission_classes = [IsAuthenticated]

    MAX_ROWS = 20000

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        fmt = str(body.get("format", "")).lower()
        if fmt not in FORMATS:
            raise ValidationError({"format": "Use csv, xlsx or pdf."})
        raw_cols = body.get("columns")
        raw_rows = body.get("rows")
        if not isinstance(raw_cols, list) or not raw_cols or not isinstance(raw_rows, list):
            raise ValidationError({"columns": "Send columns and rows."})
        if len(raw_rows) > self.MAX_ROWS:
            raise ValidationError({"rows": f"At most {self.MAX_ROWS} rows."})

        columns = []
        for i, c in enumerate(raw_cols):
            if not isinstance(c, dict) or not c.get("label"):
                raise ValidationError({"columns": "Every column needs a label."})
            kind = c.get("kind", "text")
            columns.append(Column(
                key=str(c.get("key") or f"c{i}"),
                label=str(c["label"])[:80],
                kind=kind if kind in ("text", "money", "date", "number") else "text",
                width=int(c.get("width") or (14 if kind == "money" else 18)),
            ))

        def clean(row, style=None):
            out = {col.key: row.get(col.key) for col in columns} if isinstance(row, dict) else {}
            for col in columns:
                value = out.get(col.key)
                if col.kind in ("money", "number") and value not in (None, ""):
                    try:
                        out[col.key] = Decimal(str(value))
                    except Exception:  # noqa: BLE001 - a stray label in a money column
                        out[col.key] = str(value)
                elif value is not None and not isinstance(value, str):
                    out[col.key] = str(value)
            if style:
                out["_style"] = style
            return out

        rows = [clean(r) for r in raw_rows]
        if isinstance(body.get("footer"), dict):
            rows.append(clean(body["footer"], "total"))

        def lines(name):
            value = body.get(name) or []
            return [str(v)[:200] for v in value][:10] if isinstance(value, list) else []

        title = str(body.get("title") or "Report")[:120]
        sheet = Sheet(title, columns, rows, lines("subtitle"), lines("notes"))
        return file_response(sheet, fmt, str(body.get("filename") or title))
