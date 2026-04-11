/**
 * Unit grid/list page with status filters and colour-coded badges.
 */
import { Home } from "lucide-react";
import { useState } from "react";

import StatusBadge from "@/components/StatusBadge";
import { useBuildings } from "@/hooks/useBuildings";
import { useUnitStatusSummary, useUnits } from "@/hooks/useUnits";
import type { UnitStatus } from "@/lib/types";

const STATUS_FILTERS: { value: string; label: string }[] = [
  { value: "", label: "All" },
  { value: "vacant", label: "Vacant" },
  { value: "occupied_paid", label: "Paid" },
  { value: "occupied_partial", label: "Partial" },
  { value: "occupied_unpaid", label: "Unpaid" },
  { value: "arrears", label: "Arrears" },
];

export default function UnitsPage() {
  const [statusFilter, setStatusFilter] = useState("");
  const [buildingFilter, setBuildingFilter] = useState("");

  const filters: Record<string, string> = {};
  if (statusFilter) filters.status = statusFilter;
  if (buildingFilter) filters.building = buildingFilter;

  const { data: units, isLoading } = useUnits(filters);
  const { data: summary } = useUnitStatusSummary(buildingFilter || undefined);
  const { data: buildings } = useBuildings();

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <h2 className="text-2xl font-bold text-slate-900">Units</h2>
      </div>

      {/* KPI cards */}
      {summary && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {([
            { label: "Total", value: summary.total, color: "bg-white" },
            { label: "Vacant", value: summary.vacant, color: "bg-slate-50" },
            { label: "Paid", value: summary.occupied_paid, color: "bg-green-50" },
            { label: "Partial", value: summary.occupied_partial, color: "bg-amber-50" },
            { label: "Unpaid", value: summary.occupied_unpaid, color: "bg-red-50" },
            { label: "Arrears", value: summary.arrears, color: "bg-red-100" },
          ] as const).map((card) => (
            <div
              key={card.label}
              className={`rounded-xl border border-slate-200 ${card.color} p-4`}
            >
              <p className="text-xs font-medium text-slate-500">{card.label}</p>
              <p className="mt-1 text-2xl font-bold text-slate-900">{card.value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        <select
          value={buildingFilter}
          onChange={(e) => setBuildingFilter(e.target.value)}
          className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
        >
          <option value="">All buildings</option>
          {buildings?.map((b) => (
            <option key={b.id} value={b.id}>
              {b.name}
            </option>
          ))}
        </select>

        <div className="flex gap-1">
          {STATUS_FILTERS.map((f) => (
            <button
              key={f.value}
              onClick={() => setStatusFilter(f.value)}
              className={`rounded-lg px-3 py-2 text-xs font-medium transition-colors ${
                statusFilter === f.value
                  ? "bg-slate-900 text-white"
                  : "bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {/* Unit grid */}
      {isLoading ? (
        <div className="py-12 text-center text-slate-500">Loading units...</div>
      ) : !units?.length ? (
        <div className="py-12 text-center text-slate-500">No units found.</div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {units.map((unit) => (
            <div
              key={unit.id}
              className="rounded-xl border border-slate-200 bg-white p-4 transition-shadow hover:shadow-md"
            >
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-2">
                  <Home className="h-4 w-4 text-slate-400" />
                  <span className="text-sm font-semibold text-slate-900">{unit.label}</span>
                </div>
                <StatusBadge status={unit.status as UnitStatus} />
              </div>
              <p className="mt-2 text-xs text-slate-500">{unit.building_name}</p>
              <div className="mt-3 flex items-baseline justify-between">
                <span className="text-lg font-bold text-slate-900">
                  KES {Number(unit.monthly_rent).toLocaleString()}
                </span>
                <span className="text-xs text-slate-400 capitalize">
                  {unit.unit_type.replace("_", " ")}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
