/**
 * Full dashboard with KPIs, charts, recent payments, and alerts.
 */
import {
  ArcElement,
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  Filler,
  Legend,
  LineElement,
  LinearScale,
  PointElement,
  Title,
  Tooltip,
} from "chart.js";
import { AlertTriangle, Building2, CreditCard, Home, Users } from "lucide-react";
import { Bar, Doughnut, Line } from "react-chartjs-2";

import ProgressBar from "@/components/ProgressBar";
import { useDashboard } from "@/hooks/useDashboard";

ChartJS.register(
  CategoryScale, LinearScale, BarElement, LineElement,
  PointElement, ArcElement, Filler, Title, Tooltip, Legend
);

export default function DashboardPage() {
  const { data, isLoading } = useDashboard();

  if (isLoading || !data) {
    return <div className="flex min-h-[60vh] items-center justify-center text-slate-500">Loading dashboard...</div>;
  }

  const { kpis, income_trend, occupancy, buildings, recent_payments, alerts } = data;

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold text-slate-900">Dashboard</h2>

      {/* KPI Cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KPICard icon={Home} label="Total Units" value={kpis.total_units} color="bg-blue-50 text-blue-700" />
        <KPICard icon={Building2} label="Occupied" value={kpis.occupied} sub={`${kpis.vacant} vacant`} color="bg-green-50 text-green-700" />
        <KPICard icon={Users} label="Active Tenants" value={kpis.active_tenants} color="bg-purple-50 text-purple-700" />
        <KPICard icon={AlertTriangle} label="Total Arrears" value={`KES ${kpis.total_arrears.toLocaleString()}`} color="bg-red-50 text-red-700" />
      </div>

      {/* Collection Progress */}
      <div className="rounded-xl border border-slate-200 bg-white p-5">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-slate-700">Monthly Collection</p>
            <p className="mt-1 text-xs text-slate-500">
              KES {kpis.collection_received.toLocaleString()} / KES {kpis.collection_expected.toLocaleString()}
            </p>
          </div>
          <p className="text-2xl font-bold text-slate-900">{kpis.collection_percentage}%</p>
        </div>
        <div className="mt-3">
          <ProgressBar percentage={kpis.collection_percentage} showLabel={false} />
        </div>
      </div>

      {/* Charts Row */}
      <div className="grid gap-4 lg:grid-cols-2">
        {/* Income Trend */}
        <div className="rounded-xl border border-slate-200 bg-white p-5">
          <h3 className="text-sm font-semibold text-slate-900 mb-4">12-Month Income Trend</h3>
          <Line
            data={{
              labels: income_trend.map(p => p.month),
              datasets: [{
                label: "Income (KES)",
                data: income_trend.map(p => p.amount),
                borderColor: "#2563eb",
                backgroundColor: "rgba(37,99,235,0.1)",
                fill: true,
                tension: 0.3,
              }],
            }}
            options={{
              responsive: true,
              plugins: { legend: { display: false } },
              scales: {
                y: { beginAtZero: true, ticks: { callback: (v) => `${Number(v) / 1000}k` } },
              },
            }}
          />
        </div>

        {/* Occupancy Doughnut */}
        <div className="rounded-xl border border-slate-200 bg-white p-5">
          <h3 className="text-sm font-semibold text-slate-900 mb-4">Occupancy Breakdown</h3>
          <div className="mx-auto max-w-[280px]">
            <Doughnut
              data={{
                labels: ["Paid", "Partial", "Unpaid", "Arrears", "Vacant"],
                datasets: [{
                  data: [occupancy.paid, occupancy.partial, occupancy.unpaid, occupancy.arrears, occupancy.vacant],
                  backgroundColor: ["#22c55e", "#f59e0b", "#ef4444", "#b91c1c", "#94a3b8"],
                }],
              }}
              options={{
                responsive: true,
                plugins: { legend: { position: "bottom", labels: { boxWidth: 12, padding: 16 } } },
              }}
            />
          </div>
        </div>
      </div>

      {/* Building Stacked Bar */}
      {buildings.length > 0 && (
        <div className="rounded-xl border border-slate-200 bg-white p-5">
          <h3 className="text-sm font-semibold text-slate-900 mb-4">Occupancy by Building</h3>
          <Bar
            data={{
              labels: buildings.map(b => b.name),
              datasets: [
                { label: "Occupied", data: buildings.map(b => b.occupied), backgroundColor: "#22c55e" },
                { label: "Vacant", data: buildings.map(b => b.vacant), backgroundColor: "#94a3b8" },
              ],
            }}
            options={{
              responsive: true,
              scales: { x: { stacked: true }, y: { stacked: true, beginAtZero: true } },
              plugins: { legend: { position: "bottom", labels: { boxWidth: 12 } } },
            }}
          />
        </div>
      )}

      {/* Bottom Row */}
      <div className="grid gap-4 lg:grid-cols-2">
        {/* Recent Payments */}
        <div className="rounded-xl border border-slate-200 bg-white p-5">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-900 mb-3">
            <CreditCard className="h-4 w-4" /> Recent Payments
          </h3>
          {recent_payments.length === 0 ? (
            <p className="text-sm text-slate-500">No payments yet.</p>
          ) : (
            <div className="space-y-2">
              {recent_payments.map(p => (
                <div key={p.id} className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2">
                  <div>
                    <p className="text-sm font-medium text-slate-900">{p.tenant_name}</p>
                    <p className="text-xs text-slate-500">{p.building_name} — {p.unit_label}</p>
                  </div>
                  <div className="text-right">
                    <p className="text-sm font-semibold text-green-700">KES {p.amount.toLocaleString()}</p>
                    <p className="text-xs text-slate-400">{p.payment_date}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Alerts */}
        <div className="rounded-xl border border-slate-200 bg-white p-5">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-900 mb-3">
            <AlertTriangle className="h-4 w-4 text-amber-500" /> Alerts
          </h3>
          {alerts.length === 0 ? (
            <p className="text-sm text-slate-500">No alerts. Everything looks good.</p>
          ) : (
            <div className="space-y-2">
              {alerts.map((a, i) => (
                <div
                  key={i}
                  className={`rounded-lg px-3 py-2 text-sm ${
                    a.type === "overdue" ? "bg-red-50 text-red-800" : "bg-amber-50 text-amber-800"
                  }`}
                >
                  {a.message}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function KPICard({
  icon: Icon,
  label,
  value,
  sub,
  color,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string | number;
  sub?: string;
  color: string;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5">
      <div className="flex items-center gap-3">
        <div className={`flex h-10 w-10 items-center justify-center rounded-lg ${color}`}>
          <Icon className="h-5 w-5" />
        </div>
        <div>
          <p className="text-xs font-medium text-slate-500">{label}</p>
          <p className="text-xl font-bold text-slate-900">{value}</p>
          {sub && <p className="text-xs text-slate-400">{sub}</p>}
        </div>
      </div>
    </div>
  );
}
