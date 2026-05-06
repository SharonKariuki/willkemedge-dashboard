import { Download, FileText } from "lucide-react";
import { useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, Line, LineChart,
  Pie, PieChart, ResponsiveContainer, Tooltip as RcTooltip, XAxis, YAxis,
} from "recharts";

import {
  Badge, Button, Card, CardHeader, CardTitle,
  EmptyState, PageHeader, Skeleton,
  Table, TBody, TD, TH, THead, TR,
} from "@/components/ui";
import { useBuildings } from "@/hooks/useBuildings";
import { useTenants } from "@/hooks/useTenants";
import { useUnits } from "@/hooks/useUnits";
import {
  useAgingArrears,
  useAnnualIncome,
  useArrearsReport,
  useExpiringLeases,
  useExpenseBreakdown,
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
  { key: "monthly",        label: "Monthly" },
  { key: "annual",         label: "Annual" },
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
const selectCls = "glass rounded-md px-3 py-2 text-sm text-ink-900 focus:outline-none";

// ─── Export helpers ──────────────────────────────────────────────────────────
function exportCSV(filename: string, headers: string[], rows: (string | number)[][]) {
  const lines = [headers.join(","), ...rows.map((r) => r.map((c) => `"${c}"`).join(","))];
  const blob = new Blob([lines.join("\n")], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}

function exportPDF(title: string, headers: string[], rows: (string | number)[][]) {
  const html = `<html><head><title>${title}</title>
  <style>body{font-family:-apple-system,sans-serif;font-size:12px;margin:24px;color:#181821}
  h1{font-size:18px;margin-bottom:6px}.sub{color:#636776;font-size:11px;margin-bottom:20px;text-transform:uppercase;letter-spacing:.14em}
  table{width:100%;border-collapse:collapse}th{background:#F0EDE5;text-align:left;padding:10px 12px;font-size:11px;text-transform:uppercase;letter-spacing:.1em;color:#636776}
  td{padding:10px 12px;border-bottom:1px solid #E1E1E6}</style></head><body>
  <div class="sub">Willkemedge Property Suite</div><h1>${title}</h1>
  <table><thead><tr>${headers.map((h) => `<th>${h}</th>`).join("")}</tr></thead>
  <tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody>
  </table></body></html>`;
  const win = window.open("", "_blank");
  if (!win) return;
  win.document.write(html); win.document.close(); win.print();
}

function ExportBar({ title, headers, rows, filename }: {
  title: string; headers: string[]; rows: (string | number)[][]; filename: string;
}) {
  return (
    <div className="flex gap-2">
      <Button variant="glass" size="sm" onClick={() => exportCSV(filename, headers, rows)}>
        <Download className="h-3.5 w-3.5" />CSV
      </Button>
      <Button variant="glass" size="sm" onClick={() => exportPDF(title, headers, rows)}>
        <FileText className="h-3.5 w-3.5" />PDF
      </Button>
    </div>
  );
}

function ReportTable({ headers, rows }: { headers: string[]; rows: (string | number)[][] }) {
  if (rows.length === 0)
    return <EmptyState title="No data" description="Nothing to show for the current filters." />;
  return (
    <Table>
      <THead><TR>{headers.map((h) => <TH key={h}>{h}</TH>)}</TR></THead>
      <TBody>
        {rows.map((row, i) => (
          <TR key={i}>{row.map((cell, j) => <TD key={j}>{cell}</TD>)}</TR>
        ))}
      </TBody>
    </Table>
  );
}

function BuildingFilter({ value, onChange }: { value: number | null; onChange: (v: number | null) => void }) {
  const { data: buildings } = useBuildings();
  return (
    <select value={value ?? ""} onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))} className={selectCls}>
      <option value="">All buildings</option>
      {buildings?.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
    </select>
  );
}

function SummaryCard({ label, value, tone }: { label: string; value: string; tone: "sage"|"coral"|"peri"|"ochre" }) {
  const toneClass = {
    sage: "text-sage-700 dark:text-sage-400",
    coral: "text-status-unpaid",
    peri: "text-peri-600 dark:text-peri-400",
    ochre: "text-ochre-600",
  }[tone];
  return (
    <div className="neu-sm p-4">
      <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">{label}</p>
      <p className={cn("mt-1 font-display text-xl font-semibold", toneClass)}>{value}</p>
    </div>
  );
}

function MonthYearPicker({ month, year, onMonth, onYear }: {
  month: number; year: number; onMonth: (m: number) => void; onYear: (y: number) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <select value={month} onChange={(e) => onMonth(Number(e.target.value))} className={selectCls}>
        {Array.from({ length: 12 }, (_, i) => (
          <option key={i + 1} value={i + 1}>
            {new Date(2000, i).toLocaleString("default", { month: "short" })}
          </option>
        ))}
      </select>
      <input type="number" value={year} onChange={(e) => onYear(Number(e.target.value))} className={selectCls + " w-24"} />
    </div>
  );
}

// ─── Main Page ───────────────────────────────────────────────────────────────
export default function ReportsPage() {
  const [tab, setTab] = useState<TabKey>("monthly");

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Analytics" title="Reports"
        description="All financial statements, collections, occupancy — export any view as CSV or PDF instantly." />

      <div className="glass -mx-1 flex gap-1 overflow-x-auto rounded-xl p-1">
        {TABS.map((t) => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={cn(
              "whitespace-nowrap rounded-md px-4 py-2 text-xs font-medium transition-all",
              tab === t.key ? "bg-ink-900 text-canvas shadow-float dark:bg-ink-100 dark:text-canvas"
                           : "text-ink-600 hover:text-ink-900",
            )}>
            {t.label}
          </button>
        ))}
      </div>

      <div className="animate-fade-up">
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

// ─── All tab components ───────────────────────────────────────────────────────
function MonthlyTab() {
  const now = new Date();
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [year, setYear] = useState(now.getFullYear());
  const { data, isLoading } = useMonthlyCollection(month, year);
  const headers = ["Tenant", "Unit", "Amount", "Source", "Date", "Reference"];
  const rows = data?.payments.map((p: Record<string,unknown>) => [
    p.tenant, p.unit, `KES ${Number(p.amount).toLocaleString()}`, p.source, p.date, p.reference || "—",
  ]) ?? [];
  return (
    <Card variant="glass" padding="md">
      <CardHeader>
        <div>
          <CardTitle>Monthly Collection</CardTitle>
          {data && <p className="mt-1 text-xs text-ink-500">{data.count} payments · Total <span className="font-medium text-sage-700">KES {data.total.toLocaleString()}</span></p>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <MonthYearPicker month={month} year={year} onMonth={setMonth} onYear={setYear} />
          {data && <ExportBar title={`Monthly Collection ${month}/${year}`} headers={headers} rows={rows} filename={`collection-${month}-${year}.csv`} />}
        </div>
      </CardHeader>
      {isLoading ? <Skeleton className="h-48" /> : <ReportTable headers={headers} rows={rows} />}
    </Card>
  );
}

function RentBalancesTab() {
  const now = new Date();
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [year, setYear] = useState(now.getFullYear());
  const { data, isLoading } = useRentBalances(month, year);
  const headers = ["Tenant", "Unit", "Monthly Rent", "Amount Paid", "Balance", "Status"];
  const rows = data?.balances?.map((r: Record<string,unknown>) => [
    r.tenant, r.unit, `KES ${Number(r.monthly_rent).toLocaleString()}`,
    `KES ${Number(r.paid).toLocaleString()}`, `KES ${Number(r.balance).toLocaleString()}`, r.status,
  ]) ?? [];
  return (
    <Card variant="glass" padding="md">
      <CardHeader>
        <div>
          <CardTitle>Rent Balances</CardTitle>
          {data && <p className="mt-1 text-xs text-ink-500">Outstanding: <span className="font-medium text-status-unpaid">KES {data.total_outstanding?.toLocaleString()}</span></p>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <MonthYearPicker month={month} year={year} onMonth={setMonth} onYear={setYear} />
          {data && <ExportBar title={`Rent Balances ${month}/${year}`} headers={headers} rows={rows} filename={`rent-balances-${month}-${year}.csv`} />}
        </div>
      </CardHeader>
      {isLoading ? <Skeleton className="h-48" /> : <ReportTable headers={headers} rows={rows} />}
    </Card>
  );
}

function OverpaymentsTab() {
  const now = new Date();
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [year, setYear] = useState(now.getFullYear());
  const { data, isLoading } = useRentOverpayments(month, year);
  const headers = ["Tenant", "Unit", "Expected Rent", "Amount Paid", "Overpaid By"];
  const rows = data?.overpayments?.map((r: Record<string,unknown>) => [
    r.tenant, r.unit, `KES ${Number(r.expected).toLocaleString()}`,
    `KES ${Number(r.paid).toLocaleString()}`, `KES ${Number(r.overpaid).toLocaleString()}`,
  ]) ?? [];
  return (
    <Card variant="glass" padding="md">
      <CardHeader>
        <div>
          <CardTitle>Rent Overpayments</CardTitle>
          {data && <p className="mt-1 text-xs text-ink-500">Total overpaid: <span className="font-medium text-ochre-600">KES {data.total_overpaid?.toLocaleString()}</span></p>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <MonthYearPicker month={month} year={year} onMonth={setMonth} onYear={setYear} />
          {data && <ExportBar title="Rent Overpayments" headers={headers} rows={rows} filename="overpayments.csv" />}
        </div>
      </CardHeader>
      {isLoading ? <Skeleton className="h-48" /> : <ReportTable headers={headers} rows={rows} />}
    </Card>
  );
}

function AgingTab() {
  const { data, isLoading } = useAgingArrears();
  const headers = ["Tenant", "Unit", "0–30 days", "31–60 days", "61–90 days", "90+ days", "Total Owed"];
  const rows = data?.aging?.map((r: Record<string,unknown>) => [
    r.tenant, r.unit,
    r.bucket_0_30 ? `KES ${Number(r.bucket_0_30).toLocaleString()}` : "—",
    r.bucket_31_60 ? `KES ${Number(r.bucket_31_60).toLocaleString()}` : "—",
    r.bucket_61_90 ? `KES ${Number(r.bucket_61_90).toLocaleString()}` : "—",
    r.bucket_90_plus ? `KES ${Number(r.bucket_90_plus).toLocaleString()}` : "—",
    `KES ${Number(r.total).toLocaleString()}`,
  ]) ?? [];
  return (
    <Card variant="glass" padding="md">
      <CardHeader>
        <div>
          <CardTitle>Aging Rent Balances</CardTitle>
          {data && <p className="mt-1 text-xs text-ink-500">Total outstanding: <span className="font-medium text-status-unpaid">KES {data.grand_total?.toLocaleString()}</span></p>}
        </div>
        {data && <ExportBar title="Aging Rent Balances" headers={headers} rows={rows} filename="aging-arrears.csv" />}
      </CardHeader>
      {isLoading ? <Skeleton className="h-48" /> : <ReportTable headers={headers} rows={rows} />}
    </Card>
  );
}

function ExpiringTab() {
  const { data, isLoading } = useExpiringLeases();
  const headers = ["Tenant", "Unit", "Move-in Date", "Months Active", "Status"];
  const rows = data?.leases?.map((r: Record<string,unknown>) => [
    r.tenant, r.unit, r.move_in_date, r.months_active, r.status,
  ]) ?? [];
  return (
    <Card variant="glass" padding="md">
      <CardHeader>
        <div>
          <CardTitle>Expiring Leases</CardTitle>
          <p className="mt-1 text-xs text-ink-500">Tenants approaching or past 12 months without a move-out date</p>
        </div>
        {data && <ExportBar title="Expiring Leases" headers={headers} rows={rows} filename="expiring-leases.csv" />}
      </CardHeader>
      {isLoading ? <Skeleton className="h-48" /> : <ReportTable headers={headers} rows={rows} />}
    </Card>
  );
}

function VacantUnitsTab() {
  const { data, isLoading } = useVacantUnits();
  const headers = ["Building", "Unit", "Floor", "Type", "Monthly Rent (KES)", "Status"];
  const rows = data?.units?.map((u: Record<string,unknown>) => [
    u.building, u.label, u.floor === 0 ? "Ground" : `Floor ${u.floor}`,
    u.unit_type, Number(u.monthly_rent).toLocaleString(), u.status,
  ]) ?? [];
  return (
    <Card variant="glass" padding="md">
      <CardHeader>
        <div>
          <CardTitle>Vacant & Maintenance Units</CardTitle>
          {data && <p className="mt-1 text-xs text-ink-500">{data.count} units not occupied · Potential: <span className="font-medium text-ochre-600">KES {data.potential_rent?.toLocaleString()}/mo</span></p>}
        </div>
        {data && <ExportBar title="Vacant Units" headers={headers} rows={rows} filename="vacant-units.csv" />}
      </CardHeader>
      {isLoading ? <Skeleton className="h-48" /> : <ReportTable headers={headers} rows={rows} />}
    </Card>
  );
}

function TenantStatementTab() {
  const [selectedTenant, setSelectedTenant] = useState<string>("");
  const { data: tenants } = useTenants();
  const { data, isLoading } = useTenantStatement(selectedTenant || null);
  const headers = ["Period", "Expected", "Paid", "Balance", "Status"];
  const rows = data?.rows?.map((r: Record<string,unknown>) => [
    r.period, `KES ${Number(r.expected).toLocaleString()}`,
    `KES ${Number(r.paid).toLocaleString()}`,
    `KES ${Number(r.balance).toLocaleString()}`, r.status,
  ]) ?? [];
  return (
    <Card variant="glass" padding="md">
      <CardHeader>
        <CardTitle>Tenant Statement</CardTitle>
        <div className="flex flex-wrap items-center gap-2">
          <select value={selectedTenant} onChange={(e) => setSelectedTenant(e.target.value)} className={selectCls}>
            <option value="">Select tenant…</option>
            {tenants?.map((t) => <option key={t.id} value={t.id}>{t.full_name}</option>)}
          </select>
          {data && <ExportBar title={`Statement — ${data.tenant?.name}`} headers={headers} rows={rows} filename="tenant-statement.csv" />}
        </div>
      </CardHeader>
      {selectedTenant && isLoading && <Skeleton className="h-48" />}
      {data && (
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-3">
            <SummaryCard label="Total Expected" value={`KES ${Number(data.total_expected || 0).toLocaleString()}`} tone="peri" />
            <SummaryCard label="Total Paid" value={`KES ${Number(data.total_paid || 0).toLocaleString()}`} tone="sage" />
            <SummaryCard label="Total Arrears" value={`KES ${Number(data.total_arrears || 0).toLocaleString()}`} tone="coral" />
          </div>
          <ReportTable headers={headers} rows={rows} />
        </div>
      )}
    </Card>
  );
}

function UnitStatementTab() {
  const [selectedUnit, setSelectedUnit] = useState<string>("");
  const { data: units } = useUnits();
  const { data, isLoading } = useUnitStatement(selectedUnit || null);
  const headers = ["Tenant", "Period", "Expected", "Paid", "Balance"];
  const rows = data?.rows?.map((r: Record<string,unknown>) => [
    r.tenant, r.period, `KES ${Number(r.expected).toLocaleString()}`,
    `KES ${Number(r.paid).toLocaleString()}`, `KES ${Number(r.balance).toLocaleString()}`,
  ]) ?? [];
  return (
    <Card variant="glass" padding="md">
      <CardHeader>
        <CardTitle>Property Unit Statement</CardTitle>
        <div className="flex flex-wrap items-center gap-2">
          <select value={selectedUnit} onChange={(e) => setSelectedUnit(e.target.value)} className={selectCls}>
            <option value="">Select unit…</option>
            {units?.map((u) => <option key={u.id} value={u.id}>{u.building_name} — {u.label}</option>)}
          </select>
          {data && <ExportBar title={`Unit Statement — ${data.unit?.label}`} headers={headers} rows={rows} filename="unit-statement.csv" />}
        </div>
      </CardHeader>
      {selectedUnit && isLoading && <Skeleton className="h-48" />}
      {data && <ReportTable headers={headers} rows={rows} />}
    </Card>
  );
}

function LandlordTab() {
  const now = new Date();
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [year, setYear] = useState(now.getFullYear());
  const { data, isLoading } = useLandlordStatement(month, year);
  const headers = ["Description", "Amount (KES)"];
  const rows = data?.rows?.map((r: Record<string,unknown>) => [r.description, `KES ${Number(r.amount).toLocaleString()}`]) ?? [];
  return (
    <Card variant="glass" padding="md">
      <CardHeader>
        <div>
          <CardTitle>Landlord Statement</CardTitle>
          <p className="mt-1 text-xs text-ink-500">Monthly summary for Dr. William Osoro</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <MonthYearPicker month={month} year={year} onMonth={setMonth} onYear={setYear} />
          {data && <ExportBar title={`Landlord Statement ${month}/${year}`} headers={headers} rows={rows} filename={`landlord-${month}-${year}.csv`} />}
        </div>
      </CardHeader>
      {isLoading ? <Skeleton className="h-48" /> : !data ? null : (
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-3">
            <SummaryCard label="Total Income" value={`KES ${Number(data.total_income || 0).toLocaleString()}`} tone="sage" />
            <SummaryCard label="Total Expenses" value={`KES ${Number(data.total_expenses || 0).toLocaleString()}`} tone="coral" />
            <SummaryCard label="Net to Landlord" value={`KES ${Number(data.net || 0).toLocaleString()}`} tone="ochre" />
          </div>
          <ReportTable headers={headers} rows={rows} />
        </div>
      )}
    </Card>
  );
}

function AnnualTab() {
  const [year, setYear] = useState(new Date().getFullYear());
  const { data, isLoading } = useAnnualIncome(year);
  return (
    <Card variant="glass" padding="md">
      <CardHeader>
        <div>
          <CardTitle>Annual Income · {year}</CardTitle>
          {data && <p className="mt-1 text-xs text-ink-500">Grand total <span className="font-medium text-sage-700">KES {data.grand_total.toLocaleString()}</span></p>}
        </div>
        <input type="number" value={year} onChange={(e) => setYear(Number(e.target.value))} className={selectCls + " w-24"} />
      </CardHeader>
      {isLoading ? <Skeleton className="h-64" /> : data ? (
        <div className="h-[320px]">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data.monthly.map((m: { month: number; total: number }) => ({
              month: new Date(2000, m.month - 1).toLocaleString("default", { month: "short" }), total: m.total,
            }))} margin={{ top: 10, right: 8, left: -20, bottom: 0 }}>
              <defs>
                <linearGradient id="barGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="rgb(216,154,58)" stopOpacity={0.95} />
                  <stop offset="100%" stopColor="rgb(216,154,58)" stopOpacity={0.5} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} vertical={false} />
              <XAxis dataKey="month" tickLine={false} axisLine={false} tick={AXIS_TICK} />
              <YAxis tickLine={false} axisLine={false} tick={AXIS_TICK} />
              <RcTooltip cursor={{ fill: "rgba(107,142,127,0.06)" }} contentStyle={TOOLTIP_STYLE} formatter={(v) => [`KES ${Number(v).toLocaleString()}`, "Income"]} />
              <Bar dataKey="total" fill="url(#barGrad)" radius={[8, 8, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      ) : null}
    </Card>
  );
}

function ArrearsTab() {
  const { data, isLoading } = useArrearsReport();
  const headers = ["Tenant", "Unit", "Period", "Expected", "Paid", "Balance"];
  const rows = data?.arrears.map((a: Record<string,unknown>) => [
    a.tenant, a.unit, a.period,
    `KES ${Number(a.expected).toLocaleString()}`, `KES ${Number(a.paid).toLocaleString()}`, `KES ${Number(a.balance).toLocaleString()}`,
  ]) ?? [];
  return (
    <Card variant="glass" padding="md">
      <CardHeader>
        <div>
          <CardTitle>Outstanding Arrears</CardTitle>
          {data && <p className="mt-1 text-xs text-ink-500"><span className="font-medium text-status-unpaid">KES {data.total_balance.toLocaleString()}</span> across {data.count} record{data.count === 1 ? "" : "s"}</p>}
        </div>
        {data && <ExportBar title="Outstanding Arrears" headers={headers} rows={rows} filename="arrears.csv" />}
      </CardHeader>
      {isLoading ? <Skeleton className="h-48" /> : <ReportTable headers={headers} rows={rows} />}
    </Card>
  );
}

function TenantTab() {
  const [selectedTenant, setSelectedTenant] = useState<string>("");
  const { data: tenants } = useTenants();
  const { data, isLoading } = useTenantHistory(selectedTenant || null);
  return (
    <Card variant="glass" padding="md">
      <CardHeader>
        <CardTitle>Tenant Payment History</CardTitle>
        <select value={selectedTenant} onChange={(e) => setSelectedTenant(e.target.value)} className={selectCls}>
          <option value="">Select tenant…</option>
          {tenants?.map((t) => <option key={t.id} value={t.id}>{t.full_name}</option>)}
        </select>
      </CardHeader>
      {selectedTenant && isLoading && <Skeleton className="h-48" />}
      {data && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <div>
              <p className="font-display text-xl font-semibold text-ink-900">{data.tenant.name}</p>
              <p className="text-xs text-ink-500">{data.tenant.unit}</p>
            </div>
            <div className="ml-auto text-right">
              <p className="text-[11px] uppercase tracking-wider text-ink-500">Total paid</p>
              <p className="font-display text-2xl font-semibold text-sage-700">KES {data.total_paid.toLocaleString()}</p>
            </div>
          </div>
          {data.chart_data.length > 0 && (
            <div className="h-[280px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.chart_data} margin={{ top: 10, right: 8, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} vertical={false} />
                  <XAxis dataKey="month" tickLine={false} axisLine={false} tick={AXIS_TICK} />
                  <YAxis tickLine={false} axisLine={false} tick={AXIS_TICK} />
                  <RcTooltip contentStyle={TOOLTIP_STYLE} />
                  <Bar dataKey="expected" fill="rgba(148,152,164,0.28)" radius={[6,6,0,0]} />
                  <Bar dataKey="paid" radius={[6,6,0,0]}>
                    {data.chart_data.map((d: { paid: number; expected: number }, i: number) => (
                      <Cell key={i} fill={d.paid >= d.expected ? "rgb(90,160,110)" : d.paid > 0 ? "rgb(218,163,70)" : "rgb(218,88,88)"} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

function OccupancyTab() {
  const { data, isLoading } = useOccupancyReport();
  return (
    <Card variant="glass" padding="md">
      <CardHeader>
        <CardTitle>Occupancy Overview</CardTitle>
        {data && <Badge tone="peri">{data.total_units} units total</Badge>}
      </CardHeader>
      {isLoading ? <Skeleton className="h-48" /> : data ? (
        <ReportTable
          headers={["Building", "Total", "Occupied", "Rate"]}
          rows={data.buildings.map((b: { name: string; total: number; occupied: number; rate: number }) => [b.name, b.total, b.occupied, `${b.rate}%`])}
        />
      ) : null}
    </Card>
  );
}

function MoveLogTab() {
  const { data, isLoading } = useMoveLog();
  const headers = ["Tenant", "Unit", "Move In", "Move Out", "Status"];
  const rows = data?.entries.map((e: { tenant: string; unit: string; move_in: string; move_out: string|null; status: string }) => [
    e.tenant, e.unit, e.move_in, e.move_out || "—", e.status,
  ]) ?? [];
  return (
    <Card variant="glass" padding="md">
      <CardHeader>
        <CardTitle>Move-in / Move-out log</CardTitle>
        {data && <ExportBar title="Move Log" headers={headers} rows={rows} filename="move-log.csv" />}
      </CardHeader>
      {isLoading ? <Skeleton className="h-48" /> : <ReportTable headers={headers} rows={rows} />}
    </Card>
  );
}

function ProfitLossTab() {
  const now = new Date();
  const [mode, setMode] = useState<"monthly"|"annual">("monthly");
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [year, setYear] = useState(now.getFullYear());
  const [building, setBuilding] = useState<number|null>(null);
  const monthly = useProfitLoss(month, year, building);
  const annual = useProfitLossAnnual(year, building);
  const data = mode === "monthly" ? monthly.data : annual.data;
  const isLoading = mode === "monthly" ? monthly.isLoading : annual.isLoading;
  const exportHeaders = mode === "annual"
    ? ["Month", "Income (KES)", "Expenses (KES)", "Net Profit (KES)"]
    : ["Category", "Amount (KES)"];
  const exportRows = mode === "annual" && data
    ? data.monthly.map((r: { month: number; income: number; expenses: number; net: number }) => [r.month, r.income, r.expenses, r.net])
    : data ? [["INCOME",""],["Rent Collected",data.income],["",""],["EXPENSES",""],
        ...(data.expense_breakdown??[]).map((e: { category: string; amount: number }) => [e.category, e.amount]),
        ["",""],["NET PROFIT",data.net_profit]] : [];
  return (
    <Card variant="glass" padding="md">
      <CardHeader>
        <div>
          <CardTitle>Profit & Loss</CardTitle>
          <p className="mt-1 text-xs text-ink-500">{mode === "monthly" ? `${new Date(2000,month-1).toLocaleString("default",{month:"long"})} ${year}` : `Full year ${year}`}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <BuildingFilter value={building} onChange={setBuilding} />
          <div className="glass flex overflow-hidden rounded-md">
            <button onClick={() => setMode("monthly")} className={cn("px-3 py-2 text-xs font-medium", mode === "monthly" ? "bg-ink-900 text-canvas" : "text-ink-600")}>Monthly</button>
            <button onClick={() => setMode("annual")} className={cn("px-3 py-2 text-xs font-medium", mode === "annual" ? "bg-ink-900 text-canvas" : "text-ink-600")}>Annual</button>
          </div>
          {mode === "monthly" && <MonthYearPicker month={month} year={year} onMonth={setMonth} onYear={setYear} />}
          {mode === "annual" && <input type="number" value={year} onChange={(e) => setYear(Number(e.target.value))} className={selectCls + " w-24"} />}
          {data && <ExportBar title={`P&L ${mode==="monthly"?`${month}/`:""}${year}`} headers={exportHeaders} rows={exportRows} filename={`pnl-${year}.csv`} />}
        </div>
      </CardHeader>
      {isLoading && <Skeleton className="h-48" />}
      {!isLoading && data && mode === "monthly" && (
        <div className="space-y-5">
          <div className="grid gap-3 sm:grid-cols-3">
            <SummaryCard label="Income" value={`KES ${data.income.toLocaleString()}`} tone="sage" />
            <SummaryCard label="Expenses" value={`KES ${data.total_expenses.toLocaleString()}`} tone="coral" />
            <SummaryCard label="Net Profit" value={`KES ${data.net_profit.toLocaleString()}`} tone={data.net_profit>=0?"sage":"coral"} />
          </div>
          {data.expense_breakdown?.length > 0 && (
            <ReportTable headers={["Category","Amount (KES)"]} rows={data.expense_breakdown.map((e: { category: string; amount: number }) => [e.category,`KES ${e.amount.toLocaleString()}`])} />
          )}
        </div>
      )}
      {!isLoading && data && mode === "annual" && (
        <div className="space-y-5">
          <div className="grid gap-3 sm:grid-cols-3">
            <SummaryCard label="Income" value={`KES ${data.grand_income.toLocaleString()}`} tone="sage" />
            <SummaryCard label="Expenses" value={`KES ${data.grand_expenses.toLocaleString()}`} tone="coral" />
            <SummaryCard label="Net Profit" value={`KES ${data.grand_net.toLocaleString()}`} tone={data.grand_net>=0?"sage":"coral"} />
          </div>
          <div className="h-[320px]">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={data.monthly.map((m: { month: number; income: number; expenses: number; net: number }) => ({
                month: new Date(2000,m.month-1).toLocaleString("default",{month:"short"}),
                Income:m.income, Expenses:m.expenses, Net:m.net,
              }))} margin={{top:10,right:8,left:-20,bottom:0}}>
                <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} vertical={false} />
                <XAxis dataKey="month" tickLine={false} axisLine={false} tick={AXIS_TICK} />
                <YAxis tickLine={false} axisLine={false} tick={AXIS_TICK} />
                <RcTooltip contentStyle={TOOLTIP_STYLE} />
                <Line type="monotone" dataKey="Income" stroke="rgb(216,154,58)" strokeWidth={2.5} dot={{r:3}} />
                <Line type="monotone" dataKey="Expenses" stroke="rgb(232,137,107)" strokeWidth={2.5} dot={{r:3}} />
                <Line type="monotone" dataKey="Net" stroke="rgb(139,157,195)" strokeWidth={2.5} dot={{r:3}} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </Card>
  );
}

function TrialBalanceTab() {
  const now = new Date();
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [year, setYear] = useState(now.getFullYear());
  const [building, setBuilding] = useState<number|null>(null);
  const { data, isLoading } = useTrialBalance(month, year, building);
  const exportRows = [...(data?.accounts??[]).map((a: { account: string; debit: number; credit: number }) => [a.account, a.debit||"—", a.credit||"—"]),
    ["TOTAL", data?.total_debit??0, data?.total_credit??0]];
  return (
    <Card variant="glass" padding="md">
      <CardHeader>
        <div className="flex items-center gap-3">
          <CardTitle>Trial Balance</CardTitle>
          {data && <Badge tone={data.is_balanced?"sage":"coral"} withDot>{data.is_balanced?"Balanced":"Unbalanced"}</Badge>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <BuildingFilter value={building} onChange={setBuilding} />
          <MonthYearPicker month={month} year={year} onMonth={setMonth} onYear={setYear} />
          {data && <ExportBar title={`Trial Balance ${month}/${year}`} headers={["Account","Debit (KES)","Credit (KES)"]} rows={exportRows} filename={`trial-balance-${month}-${year}.csv`} />}
        </div>
      </CardHeader>
      {isLoading && <Skeleton className="h-48" />}
      {data && (
        <Table>
          <THead><TR><TH>Account</TH><TH className="text-right">Debit</TH><TH className="text-right">Credit</TH></TR></THead>
          <TBody>
            {data.accounts.map((a: { account: string; debit: number; credit: number }, i: number) => (
              <TR key={i}>
                <TD>{a.account}</TD>
                <TD className="text-right tabular-nums">{a.debit>0?`KES ${a.debit.toLocaleString()}`:"—"}</TD>
                <TD className="text-right tabular-nums">{a.credit>0?`KES ${a.credit.toLocaleString()}`:"—"}</TD>
              </TR>
            ))}
            <TR className="border-t-2 border-ink-300 font-semibold">
              <TD className="font-semibold">TOTAL</TD>
              <TD className="text-right tabular-nums font-semibold">KES {data.total_debit.toLocaleString()}</TD>
              <TD className="text-right tabular-nums font-semibold">KES {data.total_credit.toLocaleString()}</TD>
            </TR>
          </TBody>
        </Table>
      )}
    </Card>
  );
}

function ExpenseBreakdownTab() {
  const now = new Date();
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [year, setYear] = useState(now.getFullYear());
  const [building, setBuilding] = useState<number|null>(null);
  const { data, isLoading } = useExpenseBreakdown(month, year, building);
  const exportHeaders = ["Category","Total (KES)","% of Expenses","Entries"];
  const exportRows = data?.categories.map((c: { category: string; total: number; percentage: number; count: number }) => [c.category, c.total, `${c.percentage}%`, c.count]) ?? [];
  return (
    <Card variant="glass" padding="md">
      <CardHeader>
        <CardTitle>Expense Breakdown</CardTitle>
        <div className="flex flex-wrap items-center gap-2">
          <BuildingFilter value={building} onChange={setBuilding} />
          <MonthYearPicker month={month} year={year} onMonth={setMonth} onYear={setYear} />
          {data && <ExportBar title={`Expense Breakdown ${month}/${year}`} headers={exportHeaders} rows={exportRows} filename={`expense-breakdown-${month}-${year}.csv`} />}
        </div>
      </CardHeader>
      {isLoading && <Skeleton className="h-48" />}
      {data && (
        <div className="grid gap-6 lg:grid-cols-2">
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <SummaryCard label="Total Expenses" value={`KES ${data.total_expenses.toLocaleString()}`} tone="coral" />
              <SummaryCard label="Total Income" value={`KES ${data.total_income.toLocaleString()}`} tone="sage" />
            </div>
            {data.total_income>0 && <p className="text-sm text-ink-500">Expenses are <strong className="text-status-unpaid">{data.expense_ratio}%</strong> of collection this period.</p>}
            <ReportTable headers={exportHeaders} rows={exportRows} />
          </div>
          {data.categories.length > 0 && (
            <div className="flex items-center justify-center">
              <div className="relative h-[320px] w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={data.categories} dataKey="total" nameKey="category" innerRadius={72} outerRadius={110} paddingAngle={2} stroke="none">
                      {data.categories.map((_: unknown, i: number) => <Cell key={i} fill={CHART_COLORS[i%CHART_COLORS.length]} />)}
                    </Pie>
                    <RcTooltip contentStyle={TOOLTIP_STYLE} formatter={(v) => `KES ${Number(v).toLocaleString()}`} />
                  </PieChart>
                </ResponsiveContainer>
                <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
                  <p className="text-[11px] uppercase tracking-wider text-ink-500">Total</p>
                  <p className="font-display text-xl font-semibold text-ink-900">KES {data.total_expenses.toLocaleString()}</p>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
