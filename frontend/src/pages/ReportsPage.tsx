import { useMemo, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import {
  Bar, BarChart, CartesianGrid, Cell, Line, LineChart,
  Pie, PieChart, ResponsiveContainer, Tooltip as RcTooltip, XAxis, YAxis,
} from "recharts";

import {
  Badge, Card, CardHeader, CardTitle,
  EmptyState, ErrorState, PageHeader, Skeleton,
} from "@/components/ui";
import {
  TENANT_STATUS_OPTIONS, fmtDate, kes, monthName, selectCls, useRowSearch, type Col,
} from "@/features/reports/reportFormat";
import {
  BuildingFilter, DateRange, ExportBar, FilterBar, LiveStatus, MonthRange,
  MonthYearPicker, ReportTable, SearchBox, SelectFilter, SummaryCard, YearPicker,
} from "@/features/reports/reportKit";
import { useTenants } from "@/hooks/useTenants";
import { useUnits } from "@/hooks/useUnits";
import {
  useAgingArrears,
  useAnnualIncome,
  useArrearsReport,
  useExpenseBreakdown,
  useExpiringLeases,
  useLandlordStatement,
  useMonthlyCollection,
  useMoveLog,
  useOccupancyReport,
  useProfitLoss,
  useProfitLossAnnual,
  useRentBalances,
  useRentOverpayments,
  useTenantHistory,
  useTenantStatement,
  useTrialBalance,
  useUnitStatement,
  useVacantUnits,
} from "@/hooks/useReports";
import { cn } from "@/lib/cn";

const TABS = [
  { key: "monthly",        label: "Collections" },
  { key: "annual",         label: "Annual Income" },
  { key: "arrears",        label: "Arrears" },
  { key: "rent_balances",  label: "Rent Balances" },
  { key: "overpayments",   label: "Overpayments" },
  { key: "aging",          label: "Aging Balances" },
  { key: "expiring",       label: "Expiring Leases" },
  { key: "tenant",         label: "Tenant History" },
  { key: "tenant_stmt",    label: "Tenant Statement" },
  { key: "unit_stmt",      label: "Unit Statement" },
  { key: "landlord",       label: "Landlord Statement" },
  { key: "occupancy",      label: "Occupancy" },
  { key: "vacant",         label: "Vacant Units" },
  { key: "moves",          label: "Move Log" },
  { key: "pnl",            label: "P&L" },
  { key: "trial",          label: "Trial Balance" },
  { key: "breakdown",      label: "Expense Breakdown" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

const CHART_COLORS = [
  "rgb(216,154,58)", "rgb(170,100,75)", "rgb(70,65,60)",
  "rgb(140,120,105)", "rgb(200,195,190)", "rgb(180,124,40)",
  "rgb(225,220,214)", "rgb(105,88,75)",
];
const GRID_STROKE = "rgba(128,132,150,0.15)";
const AXIS_TICK = { fill: "rgb(140,144,158)", fontSize: 11 };
const TOOLTIP_STYLE = {
  background: "rgba(255,255,255,0.95)",
  border: "1px solid rgba(0,0,0,0.06)",
  borderRadius: 12,
  fontSize: 12,
  boxShadow: "0 10px 30px rgba(0,0,0,0.08)",
};

const now = new Date();
const useMonth = () => useState(now.getMonth() + 1);
const useYear = () => useState(now.getFullYear());
const periodLabel = (month: number, year: number) => `${monthName(month)} ${year}`;
const sum = <R,>(rows: R[] | undefined, get: (r: R) => number) =>
  Math.round((rows ?? []).reduce((acc, r) => acc + Number(get(r) || 0), 0) * 100) / 100;

function statusTone(status: string) {
  switch (status) {
    case "Paid": return "paid" as const;
    case "Partial": return "partial" as const;
    case "Unpaid": return "unpaid" as const;
    case "In credit": return "sage" as const;
    default: return "neutral" as const;
  }
}

/** Card with title/summary on the left, export on the right, filters beneath. */
function ReportCard({ title, summary, exportBar, filters, children }: {
  title: ReactNode; summary?: ReactNode; exportBar?: ReactNode; filters?: ReactNode; children: ReactNode;
}) {
  return (
    <Card variant="glass" padding="md" className="min-w-0">
      <CardHeader>
        <div className="min-w-0">
          <CardTitle>{title}</CardTitle>
          {summary && <div className="mt-1 text-xs text-ink-500">{summary}</div>}
        </div>
        {exportBar}
      </CardHeader>
      {filters && <div className="mb-4">{filters}</div>}
      {children}
    </Card>
  );
}

// ─── Main Page ───────────────────────────────────────────────────────────────
export default function ReportsPage() {
  const [params, setParams] = useSearchParams();
  const requested = params.get("tab");
  const tab: TabKey = TABS.some((t) => t.key === requested) ? (requested as TabKey) : "monthly";
  const setTab = (key: TabKey) => {
    const next = new URLSearchParams(params);
    next.set("tab", key);
    setParams(next, { replace: true });
  };

  return (
    <div className="min-w-0 space-y-6">
      <PageHeader eyebrow="Analytics" title="Reports"
        description="Live figures from the books — filter any report by month, building or tenant, and export it as CSV or PDF." />

      <div className="glass -mx-1 flex gap-1 overflow-x-auto rounded-xl p-1" role="tablist">
        {TABS.map((t) => (
          <button key={t.key} role="tab" aria-selected={tab === t.key} onClick={() => setTab(t.key)}
            className={cn(
              "whitespace-nowrap rounded-md px-4 py-2 text-xs font-medium transition-all",
              tab === t.key ? "bg-ink-900 text-canvas shadow-float dark:bg-ink-100 dark:text-canvas"
                           : "text-ink-600 hover:text-ink-900",
            )}>
            {t.label}
          </button>
        ))}
      </div>

      <div className="min-w-0 animate-fade-up">
        {tab === "monthly"       && <MonthlyTab />}
        {tab === "annual"        && <AnnualTab />}
        {tab === "arrears"       && <ArrearsTab />}
        {tab === "rent_balances" && <RentBalancesTab />}
        {tab === "overpayments"  && <OverpaymentsTab />}
        {tab === "aging"         && <AgingTab />}
        {tab === "expiring"      && <ExpiringTab />}
        {tab === "tenant"        && <TenantTab />}
        {tab === "tenant_stmt"   && <TenantStatementTab />}
        {tab === "unit_stmt"     && <UnitStatementTab />}
        {tab === "landlord"      && <LandlordTab />}
        {tab === "occupancy"     && <OccupancyTab />}
        {tab === "vacant"        && <VacantUnitsTab />}
        {tab === "moves"         && <MoveLogTab />}
        {tab === "pnl"           && <ProfitLossTab />}
        {tab === "trial"         && <TrialBalanceTab />}
        {tab === "breakdown"     && <ExpenseBreakdownTab />}
      </div>
    </div>
  );
}

// ─── Collections ─────────────────────────────────────────────────────────────
interface CollectionRow {
  id: number; tenant: string; unit: string; amount: number; type: string;
  period: string; source: string; date: string; reference: string;
}
const COLLECTION_COLS: Col<CollectionRow>[] = [
  { label: "Date", get: (r) => r.date, render: (r) => fmtDate(r.date) },
  { label: "Tenant", get: (r) => r.tenant },
  { label: "Unit", get: (r) => r.unit },
  { label: "Type", get: (r) => r.type },
  { label: "For period", get: (r) => r.period },
  { label: "Source", get: (r) => r.source },
  { label: "Reference", get: (r) => r.reference || "" },
  { label: "Amount", get: (r) => r.amount, money: true },
];

function MonthlyTab() {
  const [month, setMonth] = useMonth();
  const [year, setYear] = useYear();
  const [building, setBuilding] = useState<number | null>(null);
  const [type, setType] = useState("");
  const q = useMonthlyCollection(month, year, { building, type });
  const { data } = q;
  const search = useRowSearch<CollectionRow>(data?.payments, COLLECTION_COLS);
  const title = `Collections — ${periodLabel(month, year)}`;
  return (
    <ReportCard
      title="Collections"
      summary={data && <>Cash received in {periodLabel(month, year)} · {data.count} payments · <span className="font-medium text-sage-700">{kes(data.total)}</span>
        {data.deposits_received > 0 && <> · deposits held {kes(data.deposits_received)}</>}</>}
      exportBar={<ExportBar title={title} subtitle={data?.building?.name ?? "All buildings"} filename={`collections-${year}-${month}`}
        cols={COLLECTION_COLS} rows={search.rows ?? []} footer={{ Tenant: "Total", Amount: sum(search.rows, (r) => r.amount) }} />}
      filters={<FilterBar>
        <MonthYearPicker month={month} year={year} onMonth={setMonth} onYear={setYear} />
        <BuildingFilter value={building} onChange={setBuilding} />
        <SelectFilter label="Payment type" value={type} onChange={setType}
          options={[["", "Rent, fees & other"], ["rent", "Rent only"], ["late_fee", "Late fees"], ["other", "Other income"], ["deposit", "Deposits"]]} />
        <SearchBox value={search.q} onChange={search.setQ} />
        <LiveStatus query={q} />
      </FilterBar>}
    >
      {data?.by_source?.length > 0 && (
        <div className="mb-4 flex flex-wrap gap-2">
          {data.by_source.map((s: { source: string; total: number }) => (
            <Badge key={s.source} tone="neutral">{s.source}: {kes(s.total)}</Badge>
          ))}
        </div>
      )}
      <ReportTable cols={COLLECTION_COLS} rows={search.rows} rowKey={(r) => r.id}
        footer={search.rows?.length ? { Tenant: "Total", Amount: sum(search.rows, (r) => r.amount) } : undefined}
        isLoading={q.isLoading} isError={q.isError} onRetry={() => void q.refetch()} />
    </ReportCard>
  );
}

// ─── Annual income ───────────────────────────────────────────────────────────
interface AnnualRow { month: number; total: number; rent: number; other: number; manual: number }
const ANNUAL_COLS: Col<AnnualRow>[] = [
  { label: "Month", get: (r) => monthName(r.month) },
  { label: "Rent (excl. VAT)", get: (r) => r.rent, money: true },
  { label: "Fees, other & credits", get: (r) => r.other, money: true },
  { label: "Farm & manual income", get: (r) => r.manual, money: true },
  { label: "Total", get: (r) => r.total, money: true },
];

function AnnualTab() {
  const [year, setYear] = useYear();
  const [building, setBuilding] = useState<number | null>(null);
  const q = useAnnualIncome(year, { building });
  const { data } = q;
  const rows: AnnualRow[] | undefined = data?.monthly;
  const footer = rows && {
    Month: "Total", "Rent (excl. VAT)": sum(rows, (r) => r.rent),
    "Fees, other & credits": sum(rows, (r) => r.other),
    "Farm & manual income": sum(rows, (r) => r.manual), Total: data.grand_total,
  };
  return (
    <ReportCard
      title={`Annual Income · ${year}`}
      summary={data && <>Net of VAT, the P&L's income figure · Grand total <span className="font-medium text-sage-700">{kes(data.grand_total)}</span></>}
      exportBar={<ExportBar title={`Annual Income ${year}`} subtitle={data?.building?.name ?? "All buildings"}
        filename={`annual-income-${year}`} cols={ANNUAL_COLS} rows={rows ?? []} footer={footer} />}
      filters={<FilterBar>
        <YearPicker year={year} onYear={setYear} />
        <BuildingFilter value={building} onChange={setBuilding} />
        <LiveStatus query={q} />
      </FilterBar>}
    >
      {q.isLoading && !data ? <Skeleton className="h-64" /> : q.isError && !data ? (
        <ErrorState title="Annual income could not be loaded." onRetry={() => void q.refetch()} />
      ) : rows ? (
        <div className="space-y-5">
          <div className="h-[300px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={rows.map((m) => ({ month: monthName(m.month, "short"), total: m.total }))}
                margin={{ top: 10, right: 8, left: -10, bottom: 0 }}>
                <defs>
                  <linearGradient id="barGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="rgb(216,154,58)" stopOpacity={0.95} />
                    <stop offset="100%" stopColor="rgb(216,154,58)" stopOpacity={0.5} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} vertical={false} />
                <XAxis dataKey="month" tickLine={false} axisLine={false} tick={AXIS_TICK} />
                <YAxis tickLine={false} axisLine={false} tick={AXIS_TICK} />
                <RcTooltip cursor={{ fill: "rgba(107,142,127,0.06)" }} contentStyle={TOOLTIP_STYLE} formatter={(v) => [kes(v), "Income"]} />
                <Bar dataKey="total" fill="url(#barGrad)" radius={[8, 8, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <ReportTable cols={ANNUAL_COLS} rows={rows} footer={footer} rowKey={(r) => r.month} />
        </div>
      ) : null}
    </ReportCard>
  );
}

// ─── Arrears ─────────────────────────────────────────────────────────────────
interface ArrearsRow {
  tenant_id: number; tenant: string; unit: string; status: string; phone: string;
  period: string; expected: number; paid: number; balance: number;
}
const ARREARS_COLS: Col<ArrearsRow>[] = [
  { label: "Tenant", get: (r) => r.tenant },
  { label: "Unit", get: (r) => r.unit },
  { label: "Phone", get: (r) => r.phone },
  { label: "Status", get: (r) => r.status },
  { label: "Owing since", get: (r) => r.period },
  { label: "Charged to date", get: (r) => r.expected, money: true },
  { label: "Paid to date", get: (r) => r.paid, money: true },
  { label: "Balance", get: (r) => r.balance, money: true },
];

function ArrearsTab() {
  const [building, setBuilding] = useState<number | null>(null);
  const [status, setStatus] = useState("all");
  const q = useArrearsReport({ building, status });
  const { data } = q;
  const search = useRowSearch<ArrearsRow>(data?.arrears, ARREARS_COLS);
  const footer = search.rows?.length ? { Tenant: "Total", Balance: sum(search.rows, (r) => r.balance) } : undefined;
  return (
    <ReportCard
      title="Outstanding Arrears"
      summary={data && <><span className="font-medium text-status-unpaid">{kes(data.total_balance)}</span> owed by {data.count} tenant{data.count === 1 ? "" : "s"} — the balance on each tenant's statement today</>}
      exportBar={<ExportBar title="Outstanding Arrears" subtitle={data?.building?.name ?? "All buildings"} filename="arrears"
        cols={ARREARS_COLS} rows={search.rows ?? []} footer={footer} />}
      filters={<FilterBar>
        <BuildingFilter value={building} onChange={setBuilding} />
        <SelectFilter label="Tenant status" value={status} onChange={setStatus} options={TENANT_STATUS_OPTIONS} />
        <SearchBox value={search.q} onChange={search.setQ} />
        <LiveStatus query={q} />
      </FilterBar>}
    >
      <ReportTable cols={ARREARS_COLS} rows={search.rows} footer={footer} rowKey={(r) => r.tenant_id}
        empty="Nobody owes anything for these filters."
        isLoading={q.isLoading} isError={q.isError} onRetry={() => void q.refetch()} />
    </ReportCard>
  );
}

// ─── Rent balances ───────────────────────────────────────────────────────────
interface BalanceRow {
  tenant_id: number; tenant: string; unit: string; brought_forward: number; rent: number;
  other_charges: number; charged: number; paid: number; credits: number; balance: number; status: string;
}
const BALANCE_COLS: Col<BalanceRow>[] = [
  { label: "Tenant", get: (r) => r.tenant },
  { label: "Unit", get: (r) => r.unit },
  { label: "Brought forward", get: (r) => r.brought_forward, money: true },
  { label: "Rent (incl. VAT)", get: (r) => r.rent, money: true },
  { label: "Water & other", get: (r) => r.other_charges, money: true },
  { label: "Paid", get: (r) => r.paid, money: true },
  { label: "Credits", get: (r) => r.credits, money: true },
  { label: "Balance", get: (r) => r.balance, money: true },
  { label: "Status", get: (r) => r.status, render: (r) => <Badge tone={statusTone(r.status)}>{r.status}</Badge> },
];

function RentBalancesTab() {
  const [month, setMonth] = useMonth();
  const [year, setYear] = useYear();
  const [building, setBuilding] = useState<number | null>(null);
  const [status, setStatus] = useState("all");
  const q = useRentBalances(month, year, { building, status });
  const { data } = q;
  const search = useRowSearch<BalanceRow>(data?.balances, BALANCE_COLS);
  const rows = search.rows;
  const footer = rows?.length ? {
    Tenant: "Total",
    "Brought forward": sum(rows, (r) => r.brought_forward), "Rent (incl. VAT)": sum(rows, (r) => r.rent),
    "Water & other": sum(rows, (r) => r.other_charges), Paid: sum(rows, (r) => r.paid),
    Credits: sum(rows, (r) => r.credits), Balance: sum(rows, (r) => r.balance),
  } : undefined;
  return (
    <ReportCard
      title={`Rent Balances — ${periodLabel(month, year)}`}
      summary="Brought forward + rent + water & other − paid − credits = balance at the month's end"
      exportBar={<ExportBar title={`Rent Balances — ${periodLabel(month, year)}`} subtitle={data?.building?.name ?? "All buildings"}
        filename={`rent-balances-${year}-${month}`} cols={BALANCE_COLS} rows={rows ?? []} footer={footer} />}
      filters={<FilterBar>
        <MonthYearPicker month={month} year={year} onMonth={setMonth} onYear={setYear} />
        <BuildingFilter value={building} onChange={setBuilding} />
        <SelectFilter label="Balance" value={status} onChange={setStatus}
          options={[["all", "All balances"], ["owing", "Owing"], ["credit", "In credit"], ["square", "Paid up"]]} />
        <SearchBox value={search.q} onChange={search.setQ} />
        <LiveStatus query={q} />
      </FilterBar>}
    >
      {data && (
        <div className="mb-4 grid gap-3 sm:grid-cols-3">
          <SummaryCard label="Outstanding" value={kes(data.total_outstanding)} tone="coral" />
          <SummaryCard label="In credit" value={kes(data.total_in_credit)} tone="sage" />
          <SummaryCard label="Collected this month" value={kes(data.totals?.paid)} tone="ink" hint={`${data.count} tenancies`} />
        </div>
      )}
      <ReportTable cols={BALANCE_COLS} rows={rows} footer={footer} rowKey={(r) => r.tenant_id}
        isLoading={q.isLoading} isError={q.isError} onRetry={() => void q.refetch()} />
    </ReportCard>
  );
}

// ─── Overpayments ────────────────────────────────────────────────────────────
interface OverpaidRow {
  tenant_id: number; tenant: string; unit: string; status: string;
  expected: number; paid: number; overpaid: number;
}
const OVERPAID_COLS: Col<OverpaidRow>[] = [
  { label: "Tenant", get: (r) => r.tenant },
  { label: "Unit", get: (r) => r.unit },
  { label: "Status", get: (r) => r.status },
  { label: "Charged this month", get: (r) => r.expected, money: true },
  { label: "Paid this month", get: (r) => r.paid, money: true },
  { label: "Credit carried", get: (r) => r.overpaid, money: true },
];

function OverpaymentsTab() {
  const [month, setMonth] = useMonth();
  const [year, setYear] = useYear();
  const [building, setBuilding] = useState<number | null>(null);
  const q = useRentOverpayments(month, year, { building });
  const { data } = q;
  const search = useRowSearch<OverpaidRow>(data?.overpayments, OVERPAID_COLS);
  const footer = search.rows?.length ? { Tenant: "Total", "Credit carried": sum(search.rows, (r) => r.overpaid) } : undefined;
  return (
    <ReportCard
      title={`Overpayments — ${periodLabel(month, year)}`}
      summary={data && <>Tenants who closed the month in credit · <span className="font-medium text-ochre-600">{kes(data.total_overpaid)}</span> carried forward</>}
      exportBar={<ExportBar title={`Overpayments — ${periodLabel(month, year)}`} subtitle={data?.building?.name ?? "All buildings"}
        filename={`overpayments-${year}-${month}`} cols={OVERPAID_COLS} rows={search.rows ?? []} footer={footer} />}
      filters={<FilterBar>
        <MonthYearPicker month={month} year={year} onMonth={setMonth} onYear={setYear} />
        <BuildingFilter value={building} onChange={setBuilding} />
        <SearchBox value={search.q} onChange={search.setQ} />
        <LiveStatus query={q} />
      </FilterBar>}
    >
      <ReportTable cols={OVERPAID_COLS} rows={search.rows} footer={footer} rowKey={(r) => r.tenant_id}
        empty="No tenant was in credit at the end of this month."
        isLoading={q.isLoading} isError={q.isError} onRetry={() => void q.refetch()} />
    </ReportCard>
  );
}

// ─── Aging ───────────────────────────────────────────────────────────────────
interface AgingRow {
  tenant_id: number; tenant: string; unit: string; oldest_period: string;
  bucket_0_30: number; bucket_31_60: number; bucket_61_90: number; bucket_90_plus: number; total: number;
}
const AGING_COLS: Col<AgingRow>[] = [
  { label: "Tenant", get: (r) => r.tenant },
  { label: "Unit", get: (r) => r.unit },
  { label: "Oldest", get: (r) => r.oldest_period },
  { label: "0–30 days", get: (r) => r.bucket_0_30 || null, money: true },
  { label: "31–60 days", get: (r) => r.bucket_31_60 || null, money: true },
  { label: "61–90 days", get: (r) => r.bucket_61_90 || null, money: true },
  { label: "90+ days", get: (r) => r.bucket_90_plus || null, money: true },
  { label: "Total owed", get: (r) => r.total, money: true },
];

function AgingTab() {
  const [building, setBuilding] = useState<number | null>(null);
  const [status, setStatus] = useState("all");
  const q = useAgingArrears({ building, status });
  const { data } = q;
  const search = useRowSearch<AgingRow>(data?.aging, AGING_COLS);
  const rows = search.rows;
  const footer = rows?.length ? {
    Tenant: "Total",
    "0–30 days": sum(rows, (r) => r.bucket_0_30), "31–60 days": sum(rows, (r) => r.bucket_31_60),
    "61–90 days": sum(rows, (r) => r.bucket_61_90), "90+ days": sum(rows, (r) => r.bucket_90_plus),
    "Total owed": sum(rows, (r) => r.total),
  } : undefined;
  return (
    <ReportCard
      title="Aging Balances"
      summary={data && <>How long money has been owed, oldest charge settled first · <span className="font-medium text-status-unpaid">{kes(data.grand_total)}</span></>}
      exportBar={<ExportBar title="Aging Balances" subtitle={data?.building?.name ?? "All buildings"} filename="aging-balances"
        cols={AGING_COLS} rows={rows ?? []} footer={footer} />}
      filters={<FilterBar>
        <BuildingFilter value={building} onChange={setBuilding} />
        <SelectFilter label="Tenant status" value={status} onChange={setStatus} options={TENANT_STATUS_OPTIONS} />
        <SearchBox value={search.q} onChange={search.setQ} />
        <LiveStatus query={q} />
      </FilterBar>}
    >
      <ReportTable cols={AGING_COLS} rows={rows} footer={footer} rowKey={(r) => r.tenant_id}
        empty="Nobody owes anything for these filters."
        isLoading={q.isLoading} isError={q.isError} onRetry={() => void q.refetch()} />
    </ReportCard>
  );
}

// ─── Expiring leases ─────────────────────────────────────────────────────────
interface LeaseRow {
  tenant_id: number; tenant: string; unit: string; phone: string; move_in_date: string;
  months_active: number; renewal_date: string; days_to_renewal: number; leaving_on: string | null; status: string;
}
const LEASE_COLS: Col<LeaseRow>[] = [
  { label: "Tenant", get: (r) => r.tenant },
  { label: "Unit", get: (r) => r.unit },
  { label: "Phone", get: (r) => r.phone },
  { label: "Moved in", get: (r) => r.move_in_date, render: (r) => fmtDate(r.move_in_date) },
  { label: "Months", get: (r) => r.months_active, numeric: true },
  { label: "Renews on", get: (r) => r.renewal_date, render: (r) => `${fmtDate(r.renewal_date)} (${r.days_to_renewal} d)` },
  { label: "Leaving on", get: (r) => r.leaving_on ?? "", render: (r) => fmtDate(r.leaving_on) },
  { label: "Status", get: (r) => r.status,
    render: (r) => <Badge tone={r.status === "Notice given" ? "coral" : "neutral"}>{r.status}</Badge> },
];

function ExpiringTab() {
  const [days, setDays] = useState("60");
  const [building, setBuilding] = useState<number | null>(null);
  const q = useExpiringLeases({ days, building });
  const { data } = q;
  const search = useRowSearch<LeaseRow>(data?.leases, LEASE_COLS);
  return (
    <ReportCard
      title="Expiring Leases"
      summary="Leases run a year from move-in: tenants whose anniversary falls in the window, and everyone on notice"
      exportBar={<ExportBar title={`Expiring Leases — next ${days} days`} subtitle={data?.building?.name ?? "All buildings"}
        filename="expiring-leases" cols={LEASE_COLS} rows={search.rows ?? []} />}
      filters={<FilterBar>
        <SelectFilter label="Window" value={days} onChange={setDays}
          options={[["30", "Next 30 days"], ["60", "Next 60 days"], ["90", "Next 90 days"], ["180", "Next 6 months"], ["366", "Next 12 months"]]} />
        <BuildingFilter value={building} onChange={setBuilding} lettableOnly />
        <SearchBox value={search.q} onChange={search.setQ} />
        <LiveStatus query={q} />
      </FilterBar>}
    >
      <ReportTable cols={LEASE_COLS} rows={search.rows} rowKey={(r) => r.tenant_id}
        empty="No lease renews in this window and nobody is on notice."
        isLoading={q.isLoading} isError={q.isError} onRetry={() => void q.refetch()} />
    </ReportCard>
  );
}

// ─── Vacant units ────────────────────────────────────────────────────────────
interface VacantRow {
  id: number; building: string; label: string; floor: number; unit_type: string; classification: string;
  monthly_rent: number; status: string; vacant_since: string | null; days_vacant: number | null;
}
const VACANT_COLS: Col<VacantRow>[] = [
  { label: "Building", get: (r) => r.building },
  { label: "Unit", get: (r) => r.label },
  { label: "Floor", get: (r) => (r.floor === 0 ? "Ground" : `Floor ${r.floor}`) },
  { label: "Type", get: (r) => r.unit_type },
  { label: "Use", get: (r) => r.classification },
  { label: "Status", get: (r) => r.status },
  { label: "Empty since", get: (r) => r.vacant_since ?? "",
    render: (r) => (r.vacant_since ? `${fmtDate(r.vacant_since)} (${r.days_vacant} d)` : "—") },
  { label: "Asking rent", get: (r) => r.monthly_rent, money: true },
];

function VacantUnitsTab() {
  const [building, setBuilding] = useState<number | null>(null);
  const [status, setStatus] = useState("all");
  const q = useVacantUnits({ building, status });
  const { data } = q;
  const search = useRowSearch<VacantRow>(data?.units, VACANT_COLS);
  const footer = search.rows?.length ? { Building: "Total", "Asking rent": sum(search.rows, (r) => r.monthly_rent) } : undefined;
  return (
    <ReportCard
      title="Vacant & Maintenance Units"
      summary={data && <>{data.count} lettable units without a tenant · <span className="font-medium text-ochre-600">{kes(data.potential_rent)}/month</span> asking rent (before VAT)</>}
      exportBar={<ExportBar title="Vacant Units" subtitle={data?.building?.name ?? "All buildings"} filename="vacant-units"
        cols={VACANT_COLS} rows={search.rows ?? []} footer={footer} />}
      filters={<FilterBar>
        <BuildingFilter value={building} onChange={setBuilding} lettableOnly />
        <SelectFilter label="Unit status" value={status} onChange={setStatus}
          options={[["all", "Vacant & maintenance"], ["vacant", "Vacant"], ["under_maintenance", "Under maintenance"]]} />
        <SearchBox value={search.q} onChange={search.setQ} placeholder="Search unit or building…" />
        <LiveStatus query={q} />
      </FilterBar>}
    >
      <ReportTable cols={VACANT_COLS} rows={search.rows} footer={footer} rowKey={(r) => r.id}
        empty="Every lettable unit is let."
        isLoading={q.isLoading} isError={q.isError} onRetry={() => void q.refetch()} />
    </ReportCard>
  );
}

// ─── Tenant & unit pickers ───────────────────────────────────────────────────
function TenantPicker({ value, onChange, building }: {
  value: string; onChange: (v: string) => void; building: number | null;
}) {
  const { data: tenants } = useTenants();
  const list = useMemo(
    () => (tenants ?? [])
      .filter((t) => building === null || t.building_id === building)
      .sort((a, b) => a.full_name.localeCompare(b.full_name)),
    [tenants, building],
  );
  return (
    <select aria-label="Tenant" value={value} onChange={(e) => onChange(e.target.value)} className={selectCls}>
      <option value="">Select tenant…</option>
      {list.map((t) => (
        <option key={t.id} value={t.id}>
          {t.full_name} — {t.unit_label}{t.status === "moved_out" || t.status === "archived" ? " (former)" : ""}
        </option>
      ))}
    </select>
  );
}

function UnitPicker({ value, onChange, building }: {
  value: string; onChange: (v: string) => void; building: number | null;
}) {
  const { data: units } = useUnits();
  const list = useMemo(
    () => (units ?? []).filter((u) => building === null || u.building === building),
    [units, building],
  );
  return (
    <select aria-label="Unit" value={value} onChange={(e) => onChange(e.target.value)} className={selectCls}>
      <option value="">Select unit…</option>
      {list.map((u) => <option key={u.id} value={u.id}>{u.building_name} — {u.label}</option>)}
    </select>
  );
}

// ─── Tenant history ──────────────────────────────────────────────────────────
function TenantTab() {
  const [building, setBuilding] = useState<number | null>(null);
  const [tenant, setTenant] = useState("");
  const [months, setMonths] = useState("12");
  const q = useTenantHistory(tenant || null, Number(months));
  const { data } = q;
  return (
    <ReportCard
      title="Tenant Payment History"
      summary="Charged (rent, VAT, water) against cash received, month by month"
      filters={<FilterBar>
        <BuildingFilter value={building} onChange={(b) => { setBuilding(b); setTenant(""); }} />
        <TenantPicker value={tenant} onChange={setTenant} building={building} />
        <SelectFilter label="Months" value={months} onChange={setMonths}
          options={[["6", "Last 6 months"], ["12", "Last 12 months"], ["24", "Last 24 months"], ["0", "Whole tenancy"]]} />
        {tenant && <LiveStatus query={q} />}
      </FilterBar>}
    >
      {!tenant && <EmptyState title="Choose a tenant" description="Pick a tenant above to see their payment history." />}
      {tenant && q.isLoading && <Skeleton className="h-48" />}
      {tenant && q.isError && <ErrorState title="This history could not be loaded." onRetry={() => void q.refetch()} />}
      {tenant && data && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <div className="min-w-0">
              <p className="font-display text-xl font-semibold text-ink-900">{data.tenant.name}</p>
              <p className="text-xs text-ink-500">{data.tenant.unit} · {data.tenant.status}</p>
            </div>
            <div className="ml-auto flex gap-6 text-right">
              <div>
                <p className="text-[11px] uppercase tracking-wider text-ink-500">Paid in period</p>
                <p className="font-display text-xl font-semibold text-sage-700">{kes(data.period_paid)}</p>
              </div>
              <div>
                <p className="text-[11px] uppercase tracking-wider text-ink-500">Balance today</p>
                <p className={cn("font-display text-xl font-semibold", data.balance > 0 ? "text-status-unpaid" : "text-sage-700")}>{kes(data.balance)}</p>
              </div>
            </div>
          </div>
          {data.chart_data.length > 0 ? (
            <div className="h-[280px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.chart_data} margin={{ top: 10, right: 8, left: -10, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} vertical={false} />
                  <XAxis dataKey="month" tickLine={false} axisLine={false} tick={AXIS_TICK} />
                  <YAxis tickLine={false} axisLine={false} tick={AXIS_TICK} />
                  <RcTooltip contentStyle={TOOLTIP_STYLE} formatter={(v, name) => [kes(v), name === "expected" ? "Charged" : "Paid"]} />
                  <Bar dataKey="expected" fill="rgba(148,152,164,0.28)" radius={[6, 6, 0, 0]} />
                  <Bar dataKey="paid" radius={[6, 6, 0, 0]}>
                    {data.chart_data.map((d: { paid: number; expected: number }, i: number) => (
                      <Cell key={i} fill={d.paid >= d.expected ? "rgb(90,160,110)" : d.paid > 0 ? "rgb(218,163,70)" : "rgb(218,88,88)"} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <EmptyState title="No history yet" description="Nothing has been charged or paid on this tenancy." />
          )}
        </div>
      )}
    </ReportCard>
  );
}

// ─── Statements ──────────────────────────────────────────────────────────────
interface StatementRow {
  key: number; period: string; tenant?: string; brought_forward: number; rent: number;
  other_charges: number; expected: number; paid: number; credits: number; balance: number; status: string;
}
const STATEMENT_COLS: Col<StatementRow>[] = [
  { label: "Month", get: (r) => r.period },
  { label: "Brought forward", get: (r) => r.brought_forward, money: true },
  { label: "Rent (incl. VAT)", get: (r) => r.rent, money: true },
  { label: "Water & other", get: (r) => r.other_charges, money: true },
  { label: "Paid", get: (r) => r.paid, money: true },
  { label: "Credits", get: (r) => r.credits, money: true },
  { label: "Balance", get: (r) => r.balance, money: true },
  { label: "Status", get: (r) => r.status, render: (r) => <Badge tone={statusTone(r.status)}>{r.status}</Badge> },
];
const UNIT_STATEMENT_COLS: Col<StatementRow>[] = [
  { label: "Tenant", get: (r) => r.tenant ?? "" },
  ...STATEMENT_COLS,
];

function StatementTotals({ data }: { data: { opening_balance: number; total_expected: number; total_paid: number; total_credits: number; closing_balance: number } }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
      <SummaryCard label="Opening balance" value={kes(data.opening_balance)} tone="ink" />
      <SummaryCard label="Charged" value={kes(data.total_expected)} tone="peri" />
      <SummaryCard label="Paid" value={kes(data.total_paid)} tone="sage" />
      <SummaryCard label="Credits" value={kes(data.total_credits)} tone="ochre" />
      <SummaryCard label="Closing balance" value={kes(data.closing_balance)} tone={data.closing_balance > 0 ? "coral" : "sage"} />
    </div>
  );
}

function TenantStatementTab() {
  const [building, setBuilding] = useState<number | null>(null);
  const [tenant, setTenant] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const q = useTenantStatement(tenant || null, { from, to });
  const { data } = q;
  return (
    <ReportCard
      title="Tenant Statement"
      summary={data ? <>{data.tenant.name} · {data.tenant.unit} · {data.tenant.status}</> : "Month-by-month rent roll — the figures the statement PDF prints"}
      exportBar={data && <ExportBar title={`Statement — ${data.tenant.name}`} subtitle={data.tenant.unit}
        filename={`statement-${data.tenant.name.replace(/\s+/g, "-").toLowerCase()}`} cols={STATEMENT_COLS} rows={data.rows}
        footer={{ Month: "Closing balance", Balance: data.closing_balance }} />}
      filters={<FilterBar>
        <BuildingFilter value={building} onChange={(b) => { setBuilding(b); setTenant(""); }} />
        <TenantPicker value={tenant} onChange={setTenant} building={building} />
        <MonthRange from={from} to={to} onFrom={setFrom} onTo={setTo} />
        {tenant && <LiveStatus query={q} />}
      </FilterBar>}
    >
      {!tenant && <EmptyState title="Choose a tenant" description="Pick a tenant above to see their statement." />}
      {tenant && q.isLoading && <Skeleton className="h-48" />}
      {tenant && q.isError && <ErrorState title="This statement could not be loaded." onRetry={() => void q.refetch()} />}
      {tenant && data && (
        <div className="space-y-4">
          <StatementTotals data={data} />
          <ReportTable cols={STATEMENT_COLS} rows={data.rows} rowKey={(r) => r.key}
            empty="Nothing charged or paid in these months." />
        </div>
      )}
    </ReportCard>
  );
}

function UnitStatementTab() {
  const [building, setBuilding] = useState<number | null>(null);
  const [unit, setUnit] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const q = useUnitStatement(unit || null, { from, to });
  const { data } = q;
  return (
    <ReportCard
      title="Unit Statement"
      summary={data ? <>{data.unit.building} — {data.unit.label} · {data.unit.classification} · {data.unit.status}</> : "Every tenancy a unit has had, month by month"}
      exportBar={data && <ExportBar title={`Unit Statement — ${data.unit.label}`} subtitle={data.unit.building}
        filename={`unit-statement-${data.unit.label}`} cols={UNIT_STATEMENT_COLS} rows={data.rows} />}
      filters={<FilterBar>
        <BuildingFilter value={building} onChange={(b) => { setBuilding(b); setUnit(""); }} />
        <UnitPicker value={unit} onChange={setUnit} building={building} />
        <MonthRange from={from} to={to} onFrom={setFrom} onTo={setTo} />
        {unit && <LiveStatus query={q} />}
      </FilterBar>}
    >
      {!unit && <EmptyState title="Choose a unit" description="Pick a unit above to see its statement." />}
      {unit && q.isLoading && <Skeleton className="h-48" />}
      {unit && q.isError && <ErrorState title="This statement could not be loaded." onRetry={() => void q.refetch()} />}
      {unit && data && (
        <div className="space-y-4">
          {data.tenancies.length > 0 && (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {data.tenancies.map((t: { tenant_id: number; tenant: string; status: string; move_in_date: string; move_out_date: string | null; total_paid: number; closing_balance: number }) => (
                <div key={t.tenant_id} className="neu-sm min-w-0 p-4">
                  <p className="truncate font-medium text-ink-900">{t.tenant}</p>
                  <p className="text-xs text-ink-500">{fmtDate(t.move_in_date)} – {t.move_out_date ? fmtDate(t.move_out_date) : "now"} · {t.status}</p>
                  <p className="mt-2 text-xs text-ink-500">Paid {kes(t.total_paid)} · Balance{" "}
                    <span className={t.closing_balance > 0 ? "font-medium text-status-unpaid" : "font-medium text-sage-700"}>{kes(t.closing_balance)}</span></p>
                </div>
              ))}
            </div>
          )}
          <ReportTable cols={UNIT_STATEMENT_COLS} rows={data.rows} rowKey={(r, i) => `${r.tenant}-${r.key}-${i}`}
            empty="No tenancy on this unit in these months." />
        </div>
      )}
    </ReportCard>
  );
}

// ─── Landlord statement ──────────────────────────────────────────────────────
interface LandlordRow { section: "income" | "expense" | "memo"; description: string; amount: number }
const LANDLORD_COLS: Col<LandlordRow>[] = [
  { label: "Section", get: (r) => ({ income: "Income", expense: "Expenses", memo: "Held / owed (not income)" }[r.section]) },
  { label: "Description", get: (r) => r.description },
  { label: "Amount", get: (r) => r.amount, money: true },
];

function LandlordTab() {
  const [month, setMonth] = useMonth();
  const [year, setYear] = useYear();
  const [building, setBuilding] = useState<number | null>(null);
  const q = useLandlordStatement(month, year, { building });
  const { data } = q;
  const rows: LandlordRow[] = data?.rows ?? [];
  const section = (s: LandlordRow["section"]) => rows.filter((r) => r.section === s);
  const title = `Landlord Statement — ${periodLabel(month, year)}`;
  return (
    <ReportCard
      title="Landlord Statement"
      summary={<>Monthly summary for Dr. Wilson Osoro · {data?.building?.name ?? "All properties"} · same figures as the P&L</>}
      exportBar={data && <ExportBar title={title} subtitle={data.building?.name ?? "All properties"}
        filename={`landlord-${year}-${month}`} cols={LANDLORD_COLS} rows={rows}
        footer={{ Description: "Net to landlord", Amount: data.net }} />}
      filters={<FilterBar>
        <MonthYearPicker month={month} year={year} onMonth={setMonth} onYear={setYear} />
        <BuildingFilter value={building} onChange={setBuilding} />
        <LiveStatus query={q} />
      </FilterBar>}
    >
      {q.isLoading && !data ? <Skeleton className="h-48" /> : q.isError && !data ? (
        <ErrorState title="This statement could not be loaded." onRetry={() => void q.refetch()} />
      ) : !data ? null : (
        <div className="space-y-5">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <SummaryCard label="Income" value={kes(data.total_income)} tone="sage" />
            <SummaryCard label="Expenses" value={kes(data.total_expenses)} tone="coral" />
            <SummaryCard label="Net to landlord" value={kes(data.net)} tone={data.net >= 0 ? "ochre" : "coral"} />
            <SummaryCard label="Units let" value={`${data.units_occupied} of ${data.units_total}`} tone="ink" />
          </div>
          <div className="grid gap-5 lg:grid-cols-2">
            <StatementSection title="Income" rows={section("income")} total={data.total_income} />
            <StatementSection title="Expenses" rows={section("expense")} total={data.total_expenses} />
          </div>
          {section("memo").length > 0 && (
            <StatementSection title="Received but not income" rows={section("memo")} />
          )}
        </div>
      )}
    </ReportCard>
  );
}

function StatementSection({ title, rows, total }: { title: string; rows: LandlordRow[]; total?: number }) {
  const cols: Col<LandlordRow>[] = [
    { label: title, get: (r) => r.description },
    { label: "Amount", get: (r) => r.amount, money: true },
  ];
  return (
    <ReportTable cols={cols} rows={rows} rowKey={(r) => r.description}
      footer={total === undefined ? undefined : { [title]: `Total ${title.toLowerCase()}`, Amount: total }}
      empty={`No ${title.toLowerCase()} this month.`} />
  );
}

// ─── Occupancy ───────────────────────────────────────────────────────────────
interface OccupancyRow {
  id: number; name: string; property_type: string; total: number; occupied: number;
  vacant: number; under_maintenance: number; rate: number;
}
const OCCUPANCY_COLS: Col<OccupancyRow>[] = [
  { label: "Building", get: (r) => r.name },
  { label: "Type", get: (r) => r.property_type },
  { label: "Units", get: (r) => r.total, numeric: true },
  { label: "Occupied", get: (r) => r.occupied, numeric: true },
  { label: "Vacant", get: (r) => r.vacant, numeric: true },
  { label: "Maintenance", get: (r) => r.under_maintenance, numeric: true },
  { label: "Occupancy", get: (r) => `${r.rate}%`, numeric: true },
];

function OccupancyTab() {
  const [building, setBuilding] = useState<number | null>(null);
  const q = useOccupancyReport({ building });
  const { data } = q;
  const t = data?.totals;
  const footer = t && {
    Building: "Total", Units: t.total, Occupied: t.occupied, Vacant: t.vacant,
    Maintenance: t.under_maintenance, Occupancy: `${t.rate}%`,
  };
  return (
    <ReportCard
      title="Occupancy"
      summary={t && <>{t.occupied} of {t.total} units occupied · {t.rate}%</>}
      exportBar={<ExportBar title="Occupancy" subtitle={data?.building?.name ?? "All buildings"} filename="occupancy"
        cols={OCCUPANCY_COLS} rows={data?.buildings ?? []} footer={footer} />}
      filters={<FilterBar>
        <BuildingFilter value={building} onChange={setBuilding} />
        <LiveStatus query={q} />
      </FilterBar>}
    >
      <ReportTable cols={OCCUPANCY_COLS} rows={data?.buildings} footer={footer} rowKey={(r) => r.id}
        isLoading={q.isLoading} isError={q.isError} onRetry={() => void q.refetch()} />
    </ReportCard>
  );
}

// ─── Move log ────────────────────────────────────────────────────────────────
interface MoveRow { tenant_id: number; tenant: string; unit: string; move_in: string; move_out: string | null; status: string }
const MOVE_COLS: Col<MoveRow>[] = [
  { label: "Tenant", get: (r) => r.tenant },
  { label: "Unit", get: (r) => r.unit },
  { label: "Moved in", get: (r) => r.move_in, render: (r) => fmtDate(r.move_in) },
  { label: "Moved out", get: (r) => r.move_out ?? "", render: (r) => fmtDate(r.move_out) },
  { label: "Status", get: (r) => r.status },
];

function MoveLogTab() {
  const [building, setBuilding] = useState<number | null>(null);
  const [status, setStatus] = useState("all");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const q = useMoveLog({ building, status, from, to });
  const { data } = q;
  const search = useRowSearch<MoveRow>(data?.entries, MOVE_COLS);
  return (
    <ReportCard
      title="Move-in / Move-out Log"
      summary={data && (from || to
        ? <>{data.moved_in} moved in · {data.moved_out} moved out in this window</>
        : <>{data.count} tenancies, most recent move first</>)}
      exportBar={<ExportBar title="Move Log" subtitle={[data?.building?.name ?? "All buildings", from && `from ${from}`, to && `to ${to}`].filter(Boolean).join(" ")}
        filename="move-log" cols={MOVE_COLS} rows={search.rows ?? []} />}
      filters={<FilterBar>
        <DateRange from={from} to={to} onFrom={setFrom} onTo={setTo} />
        <BuildingFilter value={building} onChange={setBuilding} />
        <SelectFilter label="Tenant status" value={status} onChange={setStatus} options={TENANT_STATUS_OPTIONS} />
        <SearchBox value={search.q} onChange={search.setQ} />
        <LiveStatus query={q} />
      </FilterBar>}
    >
      <ReportTable cols={MOVE_COLS} rows={search.rows} rowKey={(r) => r.tenant_id}
        isLoading={q.isLoading} isError={q.isError} onRetry={() => void q.refetch()} />
    </ReportCard>
  );
}

// ─── P&L ─────────────────────────────────────────────────────────────────────
interface PnlLine { label: string; amount: number }
const PNL_COLS: Col<PnlLine>[] = [
  { label: "Line", get: (r) => r.label },
  { label: "Amount", get: (r) => r.amount, money: true },
];
interface PnlMonth { month: number; income: number; expenses: number; net: number }
const PNL_ANNUAL_COLS: Col<PnlMonth>[] = [
  { label: "Month", get: (r) => monthName(r.month) },
  { label: "Income", get: (r) => r.income, money: true },
  { label: "Expenses", get: (r) => r.expenses, money: true },
  { label: "Net", get: (r) => r.net, money: true },
];

function ProfitLossTab() {
  const [mode, setMode] = useState<"monthly" | "annual">("monthly");
  const [month, setMonth] = useMonth();
  const [year, setYear] = useYear();
  const [building, setBuilding] = useState<number | null>(null);
  const monthly = useProfitLoss(month, year, building);
  const annual = useProfitLossAnnual(year, building);
  const q = mode === "monthly" ? monthly : annual;
  const data = q.data;
  const scope = data?.building_name ?? "All buildings";

  const monthlyLines: PnlLine[] = mode === "monthly" && data ? [
    ...(data.income_breakdown ?? []).map((l: PnlLine) => ({ label: `Income · ${l.label}`, amount: l.amount })),
    { label: "Total income", amount: data.income },
    ...(data.expense_breakdown ?? []).map((e: { category: string; amount: number }) => ({ label: `Expense · ${e.category}`, amount: e.amount })),
    { label: "Total expenses", amount: data.total_expenses },
    { label: "Net profit", amount: data.net_profit },
  ] : [];
  const annualFooter = mode === "annual" && data
    ? { Month: "Total", Income: data.grand_income, Expenses: data.grand_expenses, Net: data.grand_net }
    : undefined;

  return (
    <ReportCard
      title="Profit & Loss"
      summary={<>{mode === "monthly" ? periodLabel(month, year) : `Full year ${year}`} · {scope} · income net of VAT</>}
      exportBar={data && (mode === "monthly"
        ? <ExportBar title={`P&L ${periodLabel(month, year)}`} subtitle={scope} filename={`pnl-${year}-${month}`} cols={PNL_COLS} rows={monthlyLines} />
        : <ExportBar title={`P&L ${year}`} subtitle={scope} filename={`pnl-${year}`} cols={PNL_ANNUAL_COLS} rows={data.monthly ?? []} footer={annualFooter} />)}
      filters={<FilterBar>
        <div className="glass flex overflow-hidden rounded-md">
          <button onClick={() => setMode("monthly")} className={cn("px-3 py-2 text-xs font-medium", mode === "monthly" ? "bg-ink-900 text-canvas" : "text-ink-600")}>Monthly</button>
          <button onClick={() => setMode("annual")} className={cn("px-3 py-2 text-xs font-medium", mode === "annual" ? "bg-ink-900 text-canvas" : "text-ink-600")}>Annual</button>
        </div>
        {mode === "monthly"
          ? <MonthYearPicker month={month} year={year} onMonth={setMonth} onYear={setYear} />
          : <YearPicker year={year} onYear={setYear} />}
        <BuildingFilter value={building} onChange={setBuilding} />
        <LiveStatus query={q} />
      </FilterBar>}
    >
      {q.isLoading && !data && <Skeleton className="h-48" />}
      {q.isError && !data && <ErrorState title="Profit & loss could not be loaded." onRetry={() => void q.refetch()} />}
      {data && mode === "monthly" && (
        <div className="space-y-5">
          <div className="grid gap-3 sm:grid-cols-3">
            <SummaryCard label="Income" value={kes(data.income)} tone="sage" />
            <SummaryCard label="Expenses" value={kes(data.total_expenses)} tone="coral" />
            <SummaryCard label="Net profit" value={kes(data.net_profit)} tone={data.net_profit >= 0 ? "sage" : "coral"} />
          </div>
          <div className="grid gap-5 lg:grid-cols-2">
            <ReportTable cols={[{ label: "Income", get: (r: PnlLine) => r.label }, { label: "Amount", get: (r: PnlLine) => r.amount, money: true }]}
              rows={data.income_breakdown ?? []} footer={{ Income: "Total income", Amount: data.income }}
              empty="No income recorded for this period." rowKey={(r) => r.label} />
            <ReportTable cols={[{ label: "Expense", get: (r: { category: string; amount: number }) => r.category }, { label: "Amount", get: (r: { category: string; amount: number }) => r.amount, money: true }]}
              rows={data.expense_breakdown ?? []} footer={{ Expense: "Total expenses", Amount: data.total_expenses }}
              empty="No expenses recorded for this period." rowKey={(r) => r.category} />
          </div>
        </div>
      )}
      {data && mode === "annual" && (
        <div className="space-y-5">
          <div className="grid gap-3 sm:grid-cols-3">
            <SummaryCard label="Income" value={kes(data.grand_income)} tone="sage" />
            <SummaryCard label="Expenses" value={kes(data.grand_expenses)} tone="coral" />
            <SummaryCard label="Net profit" value={kes(data.grand_net)} tone={data.grand_net >= 0 ? "sage" : "coral"} />
          </div>
          <div className="h-[300px]">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={(data.monthly as PnlMonth[]).map((m) => ({
                month: monthName(m.month, "short"), Income: m.income, Expenses: m.expenses, Net: m.net,
              }))} margin={{ top: 10, right: 8, left: -10, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} vertical={false} />
                <XAxis dataKey="month" tickLine={false} axisLine={false} tick={AXIS_TICK} />
                <YAxis tickLine={false} axisLine={false} tick={AXIS_TICK} />
                <RcTooltip contentStyle={TOOLTIP_STYLE} formatter={(v) => kes(v)} />
                <Line type="monotone" dataKey="Income" stroke="rgb(216,154,58)" strokeWidth={2.5} dot={{ r: 3 }} />
                <Line type="monotone" dataKey="Expenses" stroke="rgb(232,137,107)" strokeWidth={2.5} dot={{ r: 3 }} />
                <Line type="monotone" dataKey="Net" stroke="rgb(139,157,195)" strokeWidth={2.5} dot={{ r: 3 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <ReportTable cols={PNL_ANNUAL_COLS} rows={data.monthly} footer={annualFooter} rowKey={(r) => r.month} />
        </div>
      )}
    </ReportCard>
  );
}

// ─── Trial balance ───────────────────────────────────────────────────────────
interface TbRow { account: string; debit: number; credit: number }
const TB_COLS: Col<TbRow>[] = [
  { label: "Account", get: (r) => r.account },
  { label: "Debit", get: (r) => r.debit || null, money: true },
  { label: "Credit", get: (r) => r.credit || null, money: true },
];

function TrialBalanceTab() {
  const [month, setMonth] = useMonth();
  const [year, setYear] = useYear();
  const [building, setBuilding] = useState<number | null>(null);
  const q = useTrialBalance(month, year, building);
  const { data } = q;
  const footer = data && { Account: "Total", Debit: data.total_debit, Credit: data.total_credit };
  return (
    <ReportCard
      title={<span className="flex items-center gap-3">Trial Balance
        {data && <Badge tone={data.is_balanced ? "sage" : "coral"} withDot>{data.is_balanced ? "Balanced" : "Unbalanced"}</Badge>}</span>}
      summary={`${periodLabel(month, year)} · from the general ledger`}
      exportBar={<ExportBar title={`Trial Balance ${periodLabel(month, year)}`} filename={`trial-balance-${year}-${month}`}
        cols={TB_COLS} rows={data?.accounts ?? []} footer={footer} />}
      filters={<FilterBar>
        <MonthYearPicker month={month} year={year} onMonth={setMonth} onYear={setYear} />
        <BuildingFilter value={building} onChange={setBuilding} />
        <LiveStatus query={q} />
      </FilterBar>}
    >
      <ReportTable cols={TB_COLS} rows={data?.accounts} footer={footer} rowKey={(r) => r.account}
        empty="Nothing was posted to the ledger in this period."
        isLoading={q.isLoading} isError={q.isError} onRetry={() => void q.refetch()} />
    </ReportCard>
  );
}

// ─── Expense breakdown ───────────────────────────────────────────────────────
interface CategoryRow { category: string; total: number; percentage: number; count: number }
const CATEGORY_COLS: Col<CategoryRow>[] = [
  { label: "Category", get: (r) => r.category },
  { label: "Total", get: (r) => r.total, money: true },
  { label: "% of expenses", get: (r) => `${r.percentage}%`, numeric: true },
  { label: "Entries", get: (r) => r.count, numeric: true },
];

function ExpenseBreakdownTab() {
  const [month, setMonth] = useMonth();
  const [year, setYear] = useYear();
  const [building, setBuilding] = useState<number | null>(null);
  const q = useExpenseBreakdown(month, year, building);
  const { data } = q;
  const footer = data?.categories?.length
    ? { Category: "Total", Total: data.total_expenses, Entries: sum(data.categories as CategoryRow[], (r) => r.count) }
    : undefined;
  return (
    <ReportCard
      title="Expense Breakdown"
      summary={periodLabel(month, year)}
      exportBar={<ExportBar title={`Expense Breakdown ${periodLabel(month, year)}`} filename={`expense-breakdown-${year}-${month}`}
        cols={CATEGORY_COLS} rows={data?.categories ?? []} footer={footer} />}
      filters={<FilterBar>
        <MonthYearPicker month={month} year={year} onMonth={setMonth} onYear={setYear} />
        <BuildingFilter value={building} onChange={setBuilding} />
        <LiveStatus query={q} />
      </FilterBar>}
    >
      {q.isLoading && !data && <Skeleton className="h-48" />}
      {q.isError && !data && <ErrorState title="Expense breakdown could not be loaded." onRetry={() => void q.refetch()} />}
      {data && (
        <div className="grid min-w-0 gap-6 lg:grid-cols-2">
          <div className="min-w-0 space-y-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <SummaryCard label="Total expenses" value={kes(data.total_expenses)} tone="coral" />
              <SummaryCard label="Income (P&L)" value={kes(data.total_income)} tone="sage" />
            </div>
            {data.total_income > 0 && <p className="text-sm text-ink-500">Expenses are <strong className="text-status-unpaid">{data.expense_ratio}%</strong> of income this period.</p>}
            <ReportTable cols={CATEGORY_COLS} rows={data.categories} footer={footer} rowKey={(r) => r.category}
              empty="No expenses recorded for this period." />
          </div>
          {data.categories.length > 0 && (
            <div className="flex min-w-0 items-center justify-center">
              <div className="relative h-[320px] w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={data.categories} dataKey="total" nameKey="category" innerRadius={72} outerRadius={110} paddingAngle={2} stroke="none">
                      {data.categories.map((_: unknown, i: number) => <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />)}
                    </Pie>
                    <RcTooltip contentStyle={TOOLTIP_STYLE} formatter={(v) => kes(v)} />
                  </PieChart>
                </ResponsiveContainer>
                <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
                  <p className="text-[11px] uppercase tracking-wider text-ink-500">Total</p>
                  <p className="font-display text-xl font-semibold text-ink-900">{kes(data.total_expenses)}</p>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </ReportCard>
  );
}
