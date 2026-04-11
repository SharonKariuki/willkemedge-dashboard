/**
 * Dashboard placeholder. Day 6 builds out the real KPIs, charts, and alerts.
 */
import { useAuth } from "@/hooks/useAuth";

export default function DashboardPage() {
  const { user } = useAuth();

  return (
    <div className="space-y-2">
      <h2 className="text-3xl font-bold text-slate-900">Dashboard</h2>
      <p className="text-slate-600">
        Welcome, {user?.email}. KPIs, charts, and alerts arrive on Day 6.
      </p>
      <div className="mt-6 rounded-2xl border border-dashed border-slate-300 bg-white p-10 text-center text-sm text-slate-500">
        Portfolio overview placeholder
      </div>
    </div>
  );
}
