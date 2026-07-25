import {
  BookOpen, Calculator, ChevronRight, DollarSign, FileBarChart2,
} from "lucide-react";
import { useState } from "react";

import {
  Badge, Card, EmptyState, ErrorState, PageHeader, Skeleton,
  Table, TBody, TD, TH, THead, TR,
} from "@/components/ui";
import { useReportsAccounting } from "@/hooks/useReports";
import { cn } from "@/lib/cn";

const selectCls =
  "glass rounded-md px-3 py-2 text-sm text-ink-900 focus:outline-none";

const TABS = [
  { key: "balance_sheet", label: "Balance Sheet", icon: BookOpen },
  { key: "pnl",           label: "Profit & Loss", icon: FileBarChart2 },
  { key: "ledger",        label: "General Ledger", icon: ChevronRight },
  { key: "coa",           label: "Chart of Accounts", icon: Calculator },
  { key: "petty_cash",    label: "Petty Cash", icon: DollarSign },
  { key: "budgeting",     label: "Income & Budgeting", icon: FileBarChart2 },
] as const;

type TabKey = (typeof TABS)[number]["key"];

const TONE_TEXT = {
  sage: "text-sage-700 dark:text-sage-400",
  coral: "text-status-unpaid",
  peri: "text-peri-600 dark:text-peri-400",
  ochre: "text-ochre-600",
} as const;

/** Neutral raised tile with a colored figure — matches Reports' SummaryCard. */
function StatTile({ label, value, tone }: { label: string; value: string; tone: keyof typeof TONE_TEXT }) {
  return (
    <div className="neu-sm p-4">
      <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">{label}</p>
      <p className={cn("mt-1 font-display text-xl font-semibold tabular-nums", TONE_TEXT[tone])}>{value}</p>
    </div>
  );
}

/** One line of a financial statement: label left, figure right, hairline-separated. */
function StatementRow({ label, value, total }: { label: string; value: string; total?: boolean }) {
  return (
    <div className={cn("flex items-baseline justify-between gap-4", total ? "mt-1 border-t border-ink-200 pt-3" : "py-2")}>
      <span className={cn("min-w-0", total
        ? "text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-500"
        : "text-sm text-ink-600")}>
        {label}
      </span>
      <span className={cn("whitespace-nowrap tabular-nums",
        total ? "font-display text-base font-semibold text-ink-900" : "text-sm text-ink-900")}>
        {value}
      </span>
    </div>
  );
}

const kes = (n: number) => `KES ${Number(n).toLocaleString()}`;

function BalanceSheetView({ data }: { data: Record<string, unknown> }) {
  const assets = (data.assets as Record<string, number>) ?? {};
  const liabilities = (data.liabilities as Record<string, number>) ?? {};
  const equity = (data.equity as number) ?? 0;
  const totalAssets = Object.values(assets).reduce((a, b) => a + b, 0);
  const totalLiabEquity = Object.values(liabilities).reduce((a, b) => a + b, 0) + equity;
  return (
    <div className="grid gap-x-10 gap-y-6 sm:grid-cols-2">
      <section>
        <p className="mb-1 font-display text-sm font-semibold text-ink-700">Assets</p>
        <div className="divide-y divide-ink-200/70">
          {Object.entries(assets).map(([k, v]) => (
            <StatementRow key={k} label={k} value={kes(v)} />
          ))}
        </div>
        <StatementRow label="Total Assets" value={kes(totalAssets)} total />
      </section>
      <section>
        <p className="mb-1 font-display text-sm font-semibold text-ink-700">Liabilities &amp; Equity</p>
        <div className="divide-y divide-ink-200/70">
          {Object.entries(liabilities).map(([k, v]) => (
            <StatementRow key={k} label={k} value={kes(v)} />
          ))}
          <StatementRow label="Owner Equity" value={kes(equity)} />
        </div>
        <StatementRow label="Total Liabilities + Equity" value={kes(totalLiabEquity)} total />
      </section>
    </div>
  );
}

function PnLView({ data }: { data: Record<string, unknown> }) {
  const income = Number(data.income ?? 0);
  const residential = Number(data.residential_income ?? 0);
  const commercial = Number(data.commercial_income ?? 0);
  const lateFees = Number(data.late_fees ?? 0);
  const other = Number(data.other_income ?? 0);
  const expenses = Number(data.total_expenses ?? 0);
  const net = Number(data.net_profit ?? 0);
  const breakdown = (data.expense_breakdown as { category: string; amount: number }[]) ?? [];
  const incomeRows = [
    { code: "4110", label: "Residential Rental Income", amount: residential },
    { code: "4120", label: "Commercial Rental Income", amount: commercial },
    { code: "4200", label: "Late Payment Fees / Penalties", amount: lateFees },
    { code: "—",    label: "Other Income", amount: other },
  ].filter((r) => r.amount > 0 || r.code !== "—");
  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-3">
        <StatTile label="Total Income" value={kes(income)} tone="sage" />
        <StatTile label="Total Expenses" value={kes(expenses)} tone="coral" />
        <StatTile label="Net Profit" value={kes(net)} tone={net >= 0 ? "sage" : "coral"} />
      </div>
      <div>
        <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-ink-500">Income</p>
        <Table>
          <THead><TR><TH className="w-16">Code</TH><TH>Account</TH><TH className="text-right">Amount (KES)</TH></TR></THead>
          <TBody>
            {incomeRows.map((r) => (
              <TR key={r.label}>
                <TD className="font-mono text-xs">{r.code}</TD>
                <TD>{r.label}</TD>
                <TD className="text-right tabular-nums">{Number(r.amount).toLocaleString()}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </div>
      <div>
        <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-ink-500">Expenses</p>
        {breakdown.length > 0 ? (
          <Table>
            <THead><TR><TH>Expense Category</TH><TH className="text-right">Amount (KES)</TH></TR></THead>
            <TBody>
              {breakdown.map((r) => (
                <TR key={r.category}><TD>{r.category}</TD><TD className="text-right tabular-nums">{Number(r.amount).toLocaleString()}</TD></TR>
              ))}
            </TBody>
          </Table>
        ) : (
          <p className="text-xs text-ink-400">No expenses recorded for this period.</p>
        )}
      </div>
    </div>
  );
}

function LedgerView({ data }: { data: Record<string, unknown> }) {
  const entries = (data.entries as { date: string; description: string; debit: number; credit: number; balance: number }[]) ?? [];
  return (
    <Table>
      <THead><TR><TH>Date</TH><TH>Description</TH><TH className="text-right">Debit</TH><TH className="text-right">Credit</TH><TH className="text-right">Balance</TH></TR></THead>
      <TBody>
        {entries.length === 0 ? (
          <TR><TD colSpan={5} className="text-center text-ink-400">No ledger entries for this period</TD></TR>
        ) : entries.map((e, i) => (
          <TR key={i}>
            <TD className="text-ink-500 whitespace-nowrap">{e.date}</TD>
            <TD>{e.description}</TD>
            <TD className="text-right tabular-nums">{e.debit > 0 ? `KES ${Number(e.debit).toLocaleString()}` : "—"}</TD>
            <TD className="text-right tabular-nums">{e.credit > 0 ? `KES ${Number(e.credit).toLocaleString()}` : "—"}</TD>
            <TD className={cn("text-right tabular-nums font-semibold", e.balance >= 0 ? "text-sage-700" : "text-status-unpaid")}>
              KES {Number(e.balance).toLocaleString()}
            </TD>
          </TR>
        ))}
      </TBody>
    </Table>
  );
}

type CoaAccount = {
  code: string; name: string; type: string;
  parent_code: string; is_header: boolean; balance: number | null;
};

function CoAView({ data }: { data: Record<string, unknown> }) {
  const accounts = (data.accounts as CoaAccount[]) ?? [];

  // Roll each posting account's balance up to its section header for a subtotal.
  const subtotals: Record<string, number> = {};
  let section: string | null = null;
  for (const a of accounts) {
    if (a.is_header) { section = a.code; subtotals[a.code] = 0; }
    else if (section && a.balance != null) subtotals[section] += a.balance;
  }

  return (
    <Table>
      <THead><TR><TH className="w-20">Code</TH><TH>Account Name</TH><TH>Type</TH><TH className="text-right">Balance (KES)</TH></TR></THead>
      <TBody>
        {accounts.map((a) =>
          a.is_header ? (
            <TR key={a.code} className="bg-canvas-alt hover:bg-canvas-alt">
              <TD className="font-mono text-xs font-semibold text-ink-700">{a.code}</TD>
              <TD colSpan={2} className="font-display text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-600">
                {a.name}
              </TD>
              <TD className="text-right font-display text-sm font-semibold tabular-nums text-ink-700">
                {subtotals[a.code] > 0 ? subtotals[a.code].toLocaleString() : ""}
              </TD>
            </TR>
          ) : (
            <TR key={a.code}>
              <TD className="pl-6 font-mono text-xs text-ink-500">{a.code}</TD>
              <TD className="font-medium">{a.name}</TD>
              <TD><Badge tone="peri">{a.type}</Badge></TD>
              <TD className="text-right tabular-nums">
                {a.balance == null ? "—" : Number(a.balance).toLocaleString()}
              </TD>
            </TR>
          )
        )}
      </TBody>
    </Table>
  );
}

function PettyCashView({ data }: { data: Record<string, unknown> }) {
  const entries = (data.entries as { date: string; description: string; amount: number; running_balance: number }[]) ?? [];
  const balance = Number(data.closing_balance ?? 0);
  return (
    <div className="space-y-3">
      <div className="neu-sm flex items-center justify-between p-4">
        <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">Petty Cash Balance</p>
        <p className="font-display text-2xl font-semibold tabular-nums text-ochre-600">{kes(balance)}</p>
      </div>
      <Table>
        <THead><TR><TH>Date</TH><TH>Description</TH><TH className="text-right">Cash Out (KES)</TH><TH className="text-right">Running Balance</TH></TR></THead>
        <TBody>
          {entries.length === 0 ? (
            <TR><TD colSpan={4} className="text-center text-ink-400">No petty cash transactions this period</TD></TR>
          ) : entries.map((e, i) => (
            <TR key={i}>
              <TD className="whitespace-nowrap text-ink-500">{e.date}</TD>
              <TD>{e.description}</TD>
              <TD className="text-right tabular-nums text-status-unpaid">{Number(e.amount).toLocaleString()}</TD>
              <TD className="text-right tabular-nums font-medium">{Number(e.running_balance).toLocaleString()}</TD>
            </TR>
          ))}
        </TBody>
      </Table>
    </div>
  );
}

function BudgetingView({ data }: { data: Record<string, unknown> }) {
  const rows = (data.rows as { category: string; budgeted: number; actual: number; variance: number }[]) ?? [];
  const totalBudgeted = Number(data.total_budgeted ?? 0);
  const totalActual = Number(data.total_actual ?? 0);
  const totalVariance = Number(data.total_variance ?? 0);
  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-3">
        <StatTile label="Budgeted Income" value={kes(totalBudgeted)} tone="peri" />
        <StatTile label="Actual Income" value={kes(totalActual)} tone="sage" />
        <StatTile
          label="Variance"
          value={`${totalVariance >= 0 ? "+" : "−"}${kes(Math.abs(totalVariance))}`}
          tone={totalVariance >= 0 ? "sage" : "coral"}
        />
      </div>
      <Table>
        <THead><TR><TH>Building</TH><TH className="text-right">Budgeted</TH><TH className="text-right">Actual</TH><TH className="text-right">Variance</TH></TR></THead>
        <TBody>
          {rows.map((r) => (
            <TR key={r.category}>
              <TD className="font-medium">{r.category}</TD>
              <TD className="text-right tabular-nums">{Number(r.budgeted).toLocaleString()}</TD>
              <TD className="text-right tabular-nums">{Number(r.actual).toLocaleString()}</TD>
              <TD className={cn("text-right tabular-nums font-semibold",
                r.variance >= 0 ? "text-sage-700" : "text-status-unpaid")}>
                {r.variance >= 0 ? "+" : ""}{Number(r.variance).toLocaleString()}
              </TD>
            </TR>
          ))}
        </TBody>
      </Table>
    </div>
  );
}

function AccountingContent({ tab, data }: { tab: TabKey; data: Record<string, unknown> }) {
  const note = typeof data.note === "string" ? data.note : "";
  const body =
    tab === "balance_sheet" ? <BalanceSheetView data={data} /> :
    tab === "pnl"           ? <PnLView data={data} /> :
    tab === "ledger"        ? <LedgerView data={data} /> :
    tab === "coa"           ? <CoAView data={data} /> :
    tab === "petty_cash"    ? <PettyCashView data={data} /> :
    tab === "budgeting"     ? <BudgetingView data={data} /> :
    null;
  return (
    <div key={tab} className="animate-fade-up space-y-3">
      {note && (
        <div className="hairline rounded-md bg-ochre-50/60 px-3 py-2 text-[12px] text-ink-700 dark:bg-ochre-500/10">
          {note}
        </div>
      )}
      {body}
    </div>
  );
}

/**
 * The accounting suite body (tabs + period filter + content), without a page
 * header. Rendered standalone on /accounting and embedded as a tab on the
 * Expenses page.
 */
export function AccountingSuite() {
  const now = new Date();
  const [tab, setTab] = useState<TabKey>("balance_sheet");
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [year, setYear] = useState(now.getFullYear());
  const { data, isLoading, isError, refetch } = useReportsAccounting(tab, month, year);

  return (
    <Card variant="glass" padding="md">
      <div className="space-y-4">
        {/* Sub-tabs */}
        <div className="glass -mx-1 flex gap-1 overflow-x-auto rounded-xl p-1">
          {TABS.map((t) => {
            const Icon = t.icon;
            const active = tab === t.key;
            return (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={cn(
                  "flex items-center gap-1.5 whitespace-nowrap rounded-md px-3 py-2 text-xs font-medium transition-all",
                  active ? "bg-ink-900 text-canvas shadow-float" : "text-ink-600 hover:text-ink-900",
                )}
              >
                <Icon className="h-3.5 w-3.5" />
                {t.label}
              </button>
            );
          })}
        </div>

        {/* Period filter */}
        <div className="flex flex-wrap gap-2 items-center">
          <span className="text-[11px] font-medium uppercase tracking-wider text-ink-500">Period:</span>
          <select value={month} onChange={(e) => setMonth(Number(e.target.value))} className={selectCls}>
            {Array.from({ length: 12 }, (_, i) => (
              <option key={i + 1} value={i + 1}>
                {new Date(2000, i).toLocaleString("default", { month: "long" })}
              </option>
            ))}
          </select>
          <input
            type="number" min={2020} max={2100} value={year}
            onChange={(e) => setYear(Number(e.target.value))}
            className={selectCls + " w-24"}
          />
        </div>

        {isLoading ? (
          <div className="space-y-2">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-12" />)}</div>
        ) : isError ? (
          <ErrorState
            title="Accounting data could not be loaded."
            description="This is usually temporary — try again in a moment."
            onRetry={() => refetch()}
          />
        ) : !data ? (
          <EmptyState title="No data" description="No accounting data for this period." />
        ) : (
          <AccountingContent tab={tab} data={data} />
        )}
      </div>
    </Card>
  );
}

export default function AccountingPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Finance"
        title="Accounting Suite"
        description="Balance Sheet, P&L, General Ledger, Chart of Accounts, Petty Cash, and Income & Budgeting — built on the Wilkem Ventures chart of accounts."
      />
      <AccountingSuite />
    </div>
  );
}
