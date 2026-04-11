/**
 * Reports page with tab navigation across 6 report types.
 */
import {
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  Legend,
  LinearScale,
  Title,
  Tooltip,
} from "chart.js";

import { useState } from "react";
import { Bar } from "react-chartjs-2";

import { useTenants } from "@/hooks/useTenants";
import {
  useAnnualIncome,
  useArrearsReport,
  useMonthlyCollection,
  useMoveLog,
  useOccupancyReport,
  useTenantHistory,
} from "@/hooks/useReports";

ChartJS.register(CategoryScale, LinearScale, BarElement, Title, Tooltip, Legend);

const TABS = [
  { key: "monthly", label: "Monthly Collection" },
  { key: "annual", label: "Annual Income" },
  { key: "arrears", label: "Arrears" },
  { key: "tenant", label: "Tenant History" },
  { key: "occupancy", label: "Occupancy" },
  { key: "moves", label: "Move Log" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

export default function ReportsPage() {
  const [tab, setTab] = useState<TabKey>("monthly");

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold text-slate-900">Reports</h2>

      {/* Tab nav */}
      <div className="flex flex-wrap gap-1 rounded-xl bg-slate-100 p-1">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`rounded-lg px-3 py-2 text-xs font-medium transition-colors ${
              tab === t.key ? "bg-white text-slate-900 shadow-sm" : "text-slate-600 hover:text-slate-900"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="rounded-xl border border-slate-200 bg-white p-5">
        {tab === "monthly" && <MonthlyTab />}
        {tab === "annual" && <AnnualTab />}
        {tab === "arrears" && <ArrearsTab />}
        {tab === "tenant" && <TenantTab />}
        {tab === "occupancy" && <OccupancyTab />}
        {tab === "moves" && <MoveLogTab />}
      </div>
    </div>
  );
}

function MonthlyTab() {
  const now = new Date();
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [year, setYear] = useState(now.getFullYear());
  const { data, isLoading } = useMonthlyCollection(month, year);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h3 className="text-base font-semibold text-slate-900">Monthly Collection</h3>
        <select value={month} onChange={(e) => setMonth(Number(e.target.value))} className="rounded border px-2 py-1 text-sm">
          {Array.from({ length: 12 }, (_, i) => <option key={i} value={i + 1}>{i + 1}</option>)}
        </select>
        <input type="number" value={year} onChange={(e) => setYear(Number(e.target.value))} className="w-20 rounded border px-2 py-1 text-sm" />
      </div>
      {isLoading ? <p className="text-slate-500">Loading...</p> : data && (
        <>
          <div className="flex gap-6 text-sm">
            <span className="font-medium text-slate-700">Total: <strong className="text-green-700">KES {data.total.toLocaleString()}</strong></span>
            <span className="text-slate-500">{data.count} payments</span>
          </div>
          <ReportTable
            headers={["Tenant", "Unit", "Amount", "Source", "Date", "Reference"]}
            rows={data.payments.map((p: Record<string, unknown>) => [
              p.tenant, p.unit, `KES ${Number(p.amount).toLocaleString()}`, p.source, p.date, p.reference || "—",
            ])}
          />
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
        <h3 className="text-base font-semibold text-slate-900">Annual Income</h3>
        <input type="number" value={year} onChange={(e) => setYear(Number(e.target.value))} className="w-20 rounded border px-2 py-1 text-sm" />
      </div>
      {isLoading ? <p className="text-slate-500">Loading...</p> : data && (
        <>
          <p className="text-sm font-medium text-slate-700">Grand Total: <strong className="text-green-700">KES {data.grand_total.toLocaleString()}</strong></p>
          <Bar
            data={{
              labels: data.monthly.map((m: { month: number }) => `Month ${m.month}`),
              datasets: [{
                label: "Income (KES)",
                data: data.monthly.map((m: { total: number }) => m.total),
                backgroundColor: "#2563eb",
              }],
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

  return (
    <div className="space-y-4">
      <h3 className="text-base font-semibold text-slate-900">Outstanding Arrears</h3>
      {isLoading ? <p className="text-slate-500">Loading...</p> : data && (
        <>
          <div className="flex gap-6 text-sm">
            <span className="font-medium text-red-700">Total: KES {data.total_balance.toLocaleString()}</span>
            <span className="text-slate-500">{data.count} records</span>
          </div>
          <ReportTable
            headers={["Tenant", "Unit", "Period", "Expected", "Paid", "Balance"]}
            rows={data.arrears.map((a: Record<string, unknown>) => [
              a.tenant, a.unit, a.period,
              `KES ${Number(a.expected).toLocaleString()}`,
              `KES ${Number(a.paid).toLocaleString()}`,
              `KES ${Number(a.balance).toLocaleString()}`,
            ])}
          />
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
        <h3 className="text-base font-semibold text-slate-900">Tenant Payment History</h3>
        <select value={selectedTenant} onChange={(e) => setSelectedTenant(e.target.value)} className="rounded border px-2 py-1 text-sm">
          <option value="">Select tenant...</option>
          {tenants?.map((t) => <option key={t.id} value={t.id}>{t.full_name}</option>)}
        </select>
      </div>
      {selectedTenant && isLoading && <p className="text-slate-500">Loading...</p>}
      {data && (
        <>
          <p className="text-sm text-slate-700">
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
              options={{
                responsive: true,
                plugins: { legend: { position: "bottom", labels: { boxWidth: 12 } } },
              }}
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
      <h3 className="text-base font-semibold text-slate-900">Occupancy Overview</h3>
      {isLoading ? <p className="text-slate-500">Loading...</p> : data && (
        <>
          <p className="text-sm text-slate-700">Total Units: {data.total_units}</p>
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
      <h3 className="text-base font-semibold text-slate-900">Move-in / Move-out Log</h3>
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

function ReportTable({ headers, rows }: { headers: string[]; rows: (string | number)[][] }) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead className="bg-slate-50 text-left text-xs font-medium uppercase text-slate-500">
          <tr>
            {headers.map((h) => <th key={h} className="px-4 py-3">{h}</th>)}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.length === 0 ? (
            <tr><td colSpan={headers.length} className="px-4 py-6 text-center text-slate-400">No data</td></tr>
          ) : rows.map((row, i) => (
            <tr key={i} className="hover:bg-slate-50">
              {row.map((cell, j) => <td key={j} className="px-4 py-3 text-slate-700">{cell}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
