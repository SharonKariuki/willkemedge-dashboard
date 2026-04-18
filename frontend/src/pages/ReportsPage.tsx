/**
 * Reports page with tab navigation across 9 report types.
 */
import {
  ArcElement,
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  Legend,
  LinearScale,
  Title,
  Tooltip,
} from "chart.js";

import { useState } from "react";
import { Bar, Doughnut } from "react-chartjs-2";

import { useTenants } from "@/hooks/useTenants";
import {
  useAnnualIncome,
  useArrearsReport,
  useExpenseBreakdown,
  useMoveLog,
  useMonthlyCollection,
  useOccupancyReport,
  useProfitLoss,
  useProfitLossAnnual,
  useTenantHistory,
  useTrialBalance,
} from "@/hooks/useReports";

ChartJS.register(CategoryScale, LinearScale, BarElement, ArcElement, Title, Tooltip, Legend);

const TABS = [
  { key: "monthly", label: "Monthly Collection" },
  { key: "annual", label: "Annual Income" },
  { key: "arrears", label: "Arrears" },
  { key: "tenant", label: "Tenant History" },
  { key: "occupancy", label: "Occupancy" },
  { key: "moves", label: "Move Log" },
  { key: "pnl", label: "Profit & Loss" },
  { key: "trial", label: "Trial Balance" },
  { key: "breakdown", label: "Expense Breakdown" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

// ---------------------------------------------------------------------------
// Export helpers
// ---------------------------------------------------------------------------
function exportCSV(filename: string, headers: string[], rows: (string | number)[][]) {
  const lines = [headers.join(","), ...rows.map((r) => r.map((c) => `"${c}"`).join(","))];
  const blob = new Blob([lines.join("\n")], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function exportPDF(title: string, headers: string[], rows: (string | number)[][]) {
  const html = `
    <html><head><title>${title}</title>
    <style>
      body { font-family: Arial, sans-serif; font-size: 12px; margin: 24px; }
      h1 { font-size: 16px; margin-bottom: 16px; }
      table { width: 100%; border-collapse: collapse; }
      th { background: #f1f5f9; text-align: left; padding: 8px; font-size: 11px; text-transform: uppercase; }
      td { padding: 8px; border-bottom: 1px solid #e2e8f0; }
    </style>
    </head><body>
    <h1>${title}</h1>
    <table>
      <thead><tr>${headers.map((h) => `<th>${h}</th>`).join("")}</tr></thead>
      <tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody>
    </table>
    </body></html>`;
  const win = window.open("", "_blank");
  if (!win) return;
  win.document.write(html);
  win.document.close();
  win.print();
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
export default function ReportsPage() {
  const [tab, setTab] = useState<TabKey>("monthly");

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold text-slate-900 dark:text-slate-100">Reports</h2>

      {/* Tab nav */}
      <div className="flex flex-wrap gap-1 rounded-xl bg-slate-100 p-1 dark:bg-slate-800">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`rounded-lg px-3 py-2 text-xs font-medium transition-colors ${
              tab === t.key
                ? "bg-white text-slate-900 shadow-sm dark:bg-slate-700 dark:text-slate-100"
                : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-900">
        {tab === "monthly" && <MonthlyTab />}
        {tab === "annual" && <AnnualTab />}
        {tab === "arrears" && <ArrearsTab />}
        {tab === "tenant" && <TenantTab />}
        {tab === "occupancy" && <OccupancyTab />}
        {tab === "moves" && <MoveLogTab />}
        {tab === "pnl" && <ProfitLossTab />}
        {tab === "trial" && <TrialBalanceTab />}
        {tab === "breakdown" && <ExpenseBreakdownTab />}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Existing tabs (unchanged)
// ---------------------------------------------------------------------------
function MonthlyTab() {
  const now = new Date();
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [year, setYear] = useState(now.getFullYear());
  const { data, isLoading } = useMonthlyCollection(month, year);

  const headers = ["Tenant", "Unit", "Amount", "Source", "Date", "Reference"];
  const rows = data?.payments.map((p: Record<string, unknown>) => [
    p.tenant, p.unit, `KES ${Number(p.amount).toLocaleString()}`, p.source, p.date, p.reference || "—",
  ]) ?? [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100">Monthly Collection</h3>
        <select value={month} onChange={(e) => setMonth(Number(e.target.value))} className="rounded border px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100">
          {Array.from({ length: 12 }, (_, i) => <option key={i} value={i + 1}>{i + 1}</option>)}
        </select>
        <input type="number" value={year} onChange={(e) => setYear(Number(e.target.value))} className="w-20 rounded border px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100" />
        {data && (
          <div className="ml-auto flex gap-2">
            <button onClick={() => exportCSV(`collection-${month}-${year}.csv`, headers, rows)} className="rounded border px-2 py-1 text-xs hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800">Export CSV</button>
            <button onClick={() => exportPDF(`Monthly Collection ${month}/${year}`, headers, rows)} className="rounded border px-2 py-1 text-xs hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800">Export PDF</button>
          </div>
        )}
      </div>
      {isLoading ? <p className="text-slate-500">Loading...</p> : data && (
        <>
          <div className="flex gap-6 text-sm">
            <span className="font-medium text-slate-700 dark:text-slate-300">Total: <strong className="text-green-700">KES {data.total.toLocaleString()}</strong></span>
            <span className="text-slate-500">{data.count} payments</span>
          </div>
          <ReportTable headers={headers} rows={rows} />
        </>
      )}
    </div>
  );
}

function AnnualTab() {
  const [year, setYear] = useState(new Date().getFullYear());
  const { data, isLoading } = useAnnualIncome(year);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100">Annual Income</h3>
        <input type="number" value={year} onChange={(e) => setYear(Number(e.target.value))} className="w-20 rounded border px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100" />
      </div>
      {isLoading ? <p className="text-slate-500">Loading...</p> : data && (
        <>
          <p className="text-sm font-medium text-slate-700 dark:text-slate-300">Grand Total: <strong className="text-green-700">KES {data.grand_total.toLocaleString()}</strong></p>
          <Bar
            data={{
              labels: data.monthly.map((m: { month: number }) => `Month ${m.month}`),
              datasets: [{ label: "Income (KES)", data: data.monthly.map((m: { total: number }) => m.total), backgroundColor: "#2563eb" }],
            }}
            options={{ responsive: true, plugins: { legend: { display: false } } }}
          />
        </>
      )}
    </div>
  );
}

function ArrearsTab() {
  const { data, isLoading } = useArrearsReport();

  const headers = ["Tenant", "Unit", "Period", "Expected", "Paid", "Balance"];
  const rows = data?.arrears.map((a: Record<string, unknown>) => [
    a.tenant, a.unit, a.period,
    `KES ${Number(a.expected).toLocaleString()}`,
    `KES ${Number(a.paid).toLocaleString()}`,
    `KES ${Number(a.balance).toLocaleString()}`,
  ]) ?? [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100">Outstanding Arrears</h3>
        {data && (
          <div className="ml-auto flex gap-2">
            <button onClick={() => exportCSV("arrears.csv", headers, rows)} className="rounded border px-2 py-1 text-xs hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800">Export CSV</button>
            <button onClick={() => exportPDF("Outstanding Arrears", headers, rows)} className="rounded border px-2 py-1 text-xs hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800">Export PDF</button>
          </div>
        )}
      </div>
      {isLoading ? <p className="text-slate-500">Loading...</p> : data && (
        <>
          <div className="flex gap-6 text-sm">
            <span className="font-medium text-red-700">Total: KES {data.total_balance.toLocaleString()}</span>
            <span className="text-slate-500">{data.count} records</span>
          </div>
          <ReportTable headers={headers} rows={rows} />
        </>
      )}
    </div>
  );
}

function TenantTab() {
  const [selectedTenant, setSelectedTenant] = useState<string>("");
  const { data: tenants } = useTenants();
  const { data, isLoading } = useTenantHistory(selectedTenant || null);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100">Tenant Payment History</h3>
        <select value={selectedTenant} onChange={(e) => setSelectedTenant(e.target.value)} className="rounded border px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100">
          <option value="">Select tenant...</option>
          {tenants?.map((t) => <option key={t.id} value={t.id}>{t.full_name}</option>)}
        </select>
      </div>
      {selectedTenant && isLoading && <p className="text-slate-500">Loading...</p>}
      {data && (
        <>
          <p className="text-sm text-slate-700 dark:text-slate-300">
            {data.tenant.name} — {data.tenant.unit} — Rent: KES {data.tenant.monthly_rent.toLocaleString()}
          </p>
          <p className="text-sm font-medium text-green-700">Total Paid: KES {data.total_paid.toLocaleString()}</p>
          {data.chart_data.length > 0 && (
            <Bar
              data={{
                labels: data.chart_data.map((d: { month: string }) => d.month),
                datasets: [
                  {
                    label: "Paid",
                    data: data.chart_data.map((d: { paid: number }) => d.paid),
                    backgroundColor: data.chart_data.map((d: { paid: number; expected: number }) =>
                      d.paid >= d.expected ? "#22c55e" : d.paid > 0 ? "#f59e0b" : "#ef4444"
                    ),
                  },
                  {
                    label: "Expected",
                    data: data.chart_data.map((d: { expected: number }) => d.expected),
                    backgroundColor: "rgba(100,116,139,0.15)",
                    borderColor: "#64748b",
                  },
                ],
              }}
              options={{ responsive: true, plugins: { legend: { position: "bottom", labels: { boxWidth: 12 } } } }}
            />
          )}
        </>
      )}
    </div>
  );
}

function OccupancyTab() {
  const { data, isLoading } = useOccupancyReport();

  return (
    <div className="space-y-4">
      <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100">Occupancy Overview</h3>
      {isLoading ? <p className="text-slate-500">Loading...</p> : data && (
        <>
          <p className="text-sm text-slate-700 dark:text-slate-300">Total Units: {data.total_units}</p>
          <ReportTable
            headers={["Building", "Total", "Occupied", "Occupancy Rate"]}
            rows={data.buildings.map((b: { name: string; total: number; occupied: number; rate: number }) => [
              b.name, b.total, b.occupied, `${b.rate}%`,
            ])}
          />
        </>
      )}
    </div>
  );
}

function MoveLogTab() {
  const { data, isLoading } = useMoveLog();

  return (
    <div className="space-y-4">
      <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100">Move-in / Move-out Log</h3>
      {isLoading ? <p className="text-slate-500">Loading...</p> : data && (
        <ReportTable
          headers={["Tenant", "Unit", "Move In", "Move Out", "Status"]}
          rows={data.entries.map((e: { tenant: string; unit: string; move_in: string; move_out: string | null; status: string }) => [
            e.tenant, e.unit, e.move_in, e.move_out || "—", e.status,
          ])}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// New financial tabs
// ---------------------------------------------------------------------------
function ProfitLossTab() {
  const now = new Date();
  const [mode, setMode] = useState<"monthly" | "annual">("monthly");
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [year, setYear] = useState(now.getFullYear());

  const monthly = useProfitLoss(month, year);
  const annual = useProfitLossAnnual(year);

  const data = mode === "monthly" ? monthly.data : annual.data;
  const isLoading = mode === "monthly" ? monthly.isLoading : annual.isLoading;

  // CSV / PDF helpers
  const getExportRows = () => {
    if (!data) return { headers: [] as string[], rows: [] as (string | number)[][] };
    if (mode === "annual") {
      return {
        headers: ["Month", "Income (KES)", "Expenses (KES)", "Net Profit (KES)"],
        rows: data.monthly.map((r: { month: number; income: number; expenses: number; net: number }) => [
          r.month, r.income, r.expenses, r.net,
        ]),
      };
    }
    return {
      headers: ["Category", "Amount (KES)"],
      rows: [
        ["INCOME", ""],
        ["Rent Collected", data.income],
        ["", ""],
        ["EXPENSES", ""],
        ...(data.expense_breakdown ?? []).map((e: { category: string; amount: number }) => [e.category, e.amount]),
        ["", ""],
        ["NET PROFIT", data.net_profit],
      ],
    };
  };

  const { headers: exportHeaders, rows: exportRows } = getExportRows();

  return (
    <div className="space-y-5">
      {/* Controls */}
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100">Profit & Loss</h3>
        <div className="flex rounded-lg border border-slate-200 text-sm dark:border-slate-700">
          <button
            onClick={() => setMode("monthly")}
            className={`px-3 py-1.5 ${mode === "monthly" ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900" : "text-slate-600 hover:bg-slate-50 dark:text-slate-400 dark:hover:bg-slate-800"}`}
          >
            Monthly
          </button>
          <button
            onClick={() => setMode("annual")}
            className={`px-3 py-1.5 ${mode === "annual" ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900" : "text-slate-600 hover:bg-slate-50 dark:text-slate-400 dark:hover:bg-slate-800"}`}
          >
            Annual
          </button>
        </div>
        {mode === "monthly" && (
          <select value={month} onChange={(e) => setMonth(Number(e.target.value))} className="rounded border px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100">
            {Array.from({ length: 12 }, (_, i) => (
              <option key={i + 1} value={i + 1}>
                {new Date(2000, i).toLocaleString("default", { month: "long" })}
              </option>
            ))}
          </select>
        )}
        <input type="number" value={year} onChange={(e) => setYear(Number(e.target.value))} className="w-20 rounded border px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100" />
        {data && (
          <div className="ml-auto flex gap-2">
            <button onClick={() => exportCSV(`pnl-${year}.csv`, exportHeaders, exportRows)} className="rounded border px-2 py-1 text-xs hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800">Export CSV</button>
            <button onClick={() => exportPDF(`Profit & Loss ${mode === "monthly" ? `${month}/` : ""}${year}`, exportHeaders, exportRows)} className="rounded border px-2 py-1 text-xs hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800">Export PDF</button>
          </div>
        )}
      </div>

      {isLoading && <p className="text-slate-500">Loading...</p>}

      {/* Monthly P&L */}
      {!isLoading && data && mode === "monthly" && (
        <div className="space-y-4">
          {/* Summary cards */}
          <div className="grid gap-4 sm:grid-cols-3">
            <SummaryCard label="Total Income" value={`KES ${data.income.toLocaleString()}`} color="green" />
            <SummaryCard label="Total Expenses" value={`KES ${data.total_expenses.toLocaleString()}`} color="red" />
            <SummaryCard
              label="Net Profit"
              value={`KES ${data.net_profit.toLocaleString()}`}
              color={data.net_profit >= 0 ? "green" : "red"}
            />
          </div>

          {/* Expense breakdown */}
          {data.expense_breakdown?.length > 0 && (
            <>
              <h4 className="text-sm font-semibold text-slate-700 dark:text-slate-300">Expense Breakdown</h4>
              <ReportTable
                headers={["Category", "Amount (KES)"]}
                rows={data.expense_breakdown.map((e: { category: string; amount: number }) => [
                  e.category,
                  `KES ${e.amount.toLocaleString()}`,
                ])}
              />
            </>
          )}
        </div>
      )}

      {/* Annual P&L */}
      {!isLoading && data && mode === "annual" && (
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-3">
            <SummaryCard label="Total Income" value={`KES ${data.grand_income.toLocaleString()}`} color="green" />
            <SummaryCard label="Total Expenses" value={`KES ${data.grand_expenses.toLocaleString()}`} color="red" />
            <SummaryCard
              label="Net Profit"
              value={`KES ${data.grand_net.toLocaleString()}`}
              color={data.grand_net >= 0 ? "green" : "red"}
            />
          </div>
          <Bar
            data={{
              labels: data.monthly.map((m: { month: number }) => `Month ${m.month}`),
              datasets: [
                { label: "Income", data: data.monthly.map((m: { income: number }) => m.income), backgroundColor: "#22c55e" },
                { label: "Expenses", data: data.monthly.map((m: { expenses: number }) => m.expenses), backgroundColor: "#ef4444" },
                { label: "Net", data: data.monthly.map((m: { net: number }) => m.net), backgroundColor: "#3b82f6" },
              ],
            }}
            options={{ responsive: true, plugins: { legend: { position: "bottom", labels: { boxWidth: 12 } } } }}
          />
        </div>
      )}
    </div>
  );
}

function TrialBalanceTab() {
  const now = new Date();
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [year, setYear] = useState(now.getFullYear());
  const { data, isLoading } = useTrialBalance(month, year);

  const exportHeaders = ["Account", "Debit (KES)", "Credit (KES)"];
  const exportRows = [
    ...(data?.accounts ?? []).map((a: { account: string; debit: number; credit: number }) => [
      a.account, a.debit || "—", a.credit || "—",
    ]),
    ["TOTAL", data?.total_debit ?? 0, data?.total_credit ?? 0],
  ];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100">Trial Balance</h3>
        <select value={month} onChange={(e) => setMonth(Number(e.target.value))} className="rounded border px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100">
          {Array.from({ length: 12 }, (_, i) => (
            <option key={i + 1} value={i + 1}>
              {new Date(2000, i).toLocaleString("default", { month: "long" })}
            </option>
          ))}
        </select>
        <input type="number" value={year} onChange={(e) => setYear(Number(e.target.value))} className="w-20 rounded border px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100" />
        {data && (
          <div className="ml-auto flex gap-2">
            <button onClick={() => exportCSV(`trial-balance-${month}-${year}.csv`, exportHeaders, exportRows)} className="rounded border px-2 py-1 text-xs hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800">Export CSV</button>
            <button onClick={() => exportPDF(`Trial Balance ${month}/${year}`, exportHeaders, exportRows)} className="rounded border px-2 py-1 text-xs hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800">Export PDF</button>
          </div>
        )}
      </div>

      {/* Balance check badge */}
      {data && (
        <div className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-medium ${
          data.is_balanced
            ? "bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-400"
            : "bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400"
        }`}>
          {data.is_balanced ? "✓ Books are balanced" : "✗ Books are not balanced — check for missing entries"}
        </div>
      )}

      {isLoading && <p className="text-slate-500">Loading...</p>}

      {data && (
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs font-medium uppercase text-slate-500 dark:bg-slate-800 dark:text-slate-400">
              <tr>
                <th className="px-4 py-3">Account</th>
                <th className="px-4 py-3 text-right">Debit (KES)</th>
                <th className="px-4 py-3 text-right">Credit (KES)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {data.accounts.map((a: { account: string; debit: number; credit: number }, i: number) => (
                <tr key={i} className="hover:bg-slate-50 dark:hover:bg-slate-800">
                  <td className="px-4 py-3 text-slate-700 dark:text-slate-300">{a.account}</td>
                  <td className="px-4 py-3 text-right text-slate-700 dark:text-slate-300">
                    {a.debit > 0 ? `KES ${a.debit.toLocaleString()}` : "—"}
                  </td>
                  <td className="px-4 py-3 text-right text-slate-700 dark:text-slate-300">
                    {a.credit > 0 ? `KES ${a.credit.toLocaleString()}` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot className="bg-slate-50 font-semibold dark:bg-slate-800">
              <tr>
                <td className="px-4 py-3 text-slate-900 dark:text-slate-100">TOTAL</td>
                <td className="px-4 py-3 text-right text-slate-900 dark:text-slate-100">
                  KES {data.total_debit.toLocaleString()}
                </td>
                <td className="px-4 py-3 text-right text-slate-900 dark:text-slate-100">
                  KES {data.total_credit.toLocaleString()}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}
    </div>
  );
}

function ExpenseBreakdownTab() {
  const now = new Date();
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [year, setYear] = useState(now.getFullYear());
  const { data, isLoading } = useExpenseBreakdown(month, year);

  const exportHeaders = ["Category", "Total (KES)", "% of Expenses", "Entries"];
  const exportRows = (data?.categories ?? []).map((c: { category: string; total: number; percentage: number; count: number }) => [
    c.category, c.total, `${c.percentage}%`, c.count,
  ]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100">Expense Breakdown</h3>
        <select value={month} onChange={(e) => setMonth(Number(e.target.value))} className="rounded border px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100">
          {Array.from({ length: 12 }, (_, i) => (
            <option key={i + 1} value={i + 1}>
              {new Date(2000, i).toLocaleString("default", { month: "long" })}
            </option>
          ))}
        </select>
        <input type="number" value={year} onChange={(e) => setYear(Number(e.target.value))} className="w-20 rounded border px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100" />
        {data && (
          <div className="ml-auto flex gap-2">
            <button onClick={() => exportCSV(`expense-breakdown-${month}-${year}.csv`, exportHeaders, exportRows)} className="rounded border px-2 py-1 text-xs hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800">Export CSV</button>
            <button onClick={() => exportPDF(`Expense Breakdown ${month}/${year}`, exportHeaders, exportRows)} className="rounded border px-2 py-1 text-xs hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800">Export PDF</button>
          </div>
        )}
      </div>

      {isLoading && <p className="text-slate-500">Loading...</p>}

      {data && (
        <div className="grid gap-6 lg:grid-cols-2">
          {/* Summary stats */}
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <SummaryCard label="Total Expenses" value={`KES ${data.total_expenses.toLocaleString()}`} color="red" />
              <SummaryCard label="Total Income" value={`KES ${data.total_income.toLocaleString()}`} color="green" />
            </div>
            {data.total_income > 0 && (
              <p className="text-sm text-slate-600 dark:text-slate-400">
                Expenses are <strong className="text-red-600">{data.expense_ratio}%</strong> of rent collected this period.
              </p>
            )}
            <ReportTable headers={exportHeaders} rows={exportRows} />
          </div>

          {/* Doughnut chart */}
          {data.categories.length > 0 && (
            <div className="flex items-center justify-center">
              <div className="w-64">
                <Doughnut
                  data={{
                    labels: data.categories.map((c: { category: string }) => c.category),
                    datasets: [{
                      data: data.categories.map((c: { total: number }) => c.total),
                      backgroundColor: [
                        "#3b82f6", "#ef4444", "#f59e0b", "#22c55e",
                        "#8b5cf6", "#ec4899", "#14b8a6", "#f97316",
                      ],
                      borderWidth: 2,
                    }],
                  }}
                  options={{
                    responsive: true,
                    plugins: {
                      legend: { position: "bottom", labels: { boxWidth: 12, font: { size: 11 } } },
                    },
                  }}
                />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared components
// ---------------------------------------------------------------------------
function SummaryCard({ label, value, color }: { label: string; value: string; color: "green" | "red" | "blue" }) {
  const colorClasses = {
    green: "text-green-700 dark:text-green-400",
    red: "text-red-600 dark:text-red-400",
    blue: "text-blue-700 dark:text-blue-400",
  };
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-700 dark:bg-slate-800">
      <p className="text-xs font-medium text-slate-500 dark:text-slate-400">{label}</p>
      <p className={`mt-1 text-lg font-bold ${colorClasses[color]}`}>{value}</p>
    </div>
  );
}

function ReportTable({ headers, rows }: { headers: string[]; rows: (string | number)[][] }) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead className="bg-slate-50 text-left text-xs font-medium uppercase text-slate-500 dark:bg-slate-800 dark:text-slate-400">
          <tr>
            {headers.map((h) => <th key={h} className="px-4 py-3">{h}</th>)}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
          {rows.length === 0 ? (
            <tr><td colSpan={headers.length} className="px-4 py-6 text-center text-slate-400">No data</td></tr>
          ) : rows.map((row, i) => (
            <tr key={i} className="hover:bg-slate-50 dark:hover:bg-slate-800">
              {row.map((cell, j) => <td key={j} className="px-4 py-3 text-slate-700 dark:text-slate-300">{cell}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
