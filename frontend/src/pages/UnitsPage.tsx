import { Home, Search, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import StatusBadge from "@/components/StatusBadge";
import {
  Badge,
  Card,
  EmptyState,
  Input,
  PageHeader,
  Skeleton,
} from "@/components/ui";
import { useBuildings } from "@/hooks/useBuildings";
import { useUnitStatusSummary, useUnits } from "@/hooks/useUnits";
import { cn } from "@/lib/cn";
import type { UnitStatus } from "@/lib/types";

const STATUS_FILTERS = [
  { value: "", label: "All", tone: "neutral" as const },
  { value: "vacant", label: "Vacant", tone: "vacant" as const },
  { value: "occupied_paid", label: "Paid", tone: "paid" as const },
  { value: "occupied_partial", label: "Partial", tone: "partial" as const },
  { value: "occupied_unpaid", label: "Unpaid", tone: "unpaid" as const },
  { value: "arrears", label: "Arrears", tone: "unpaid" as const },
];

const STATUS_RAIL: Record<UnitStatus, string> = {
  vacant: "bg-status-vacant",
  occupied_paid: "bg-status-paid",
  occupied_partial: "bg-status-partial",
  occupied_unpaid: "bg-status-unpaid",
  arrears: "bg-status-unpaid",
};

export default function UnitsPage() {
  const [searchParams] = useSearchParams();
  const [statusFilter, setStatusFilter] = useState("");
  const [buildingFilter, setBuildingFilter] = useState("");
  const [search, setSearch] = useState(searchParams.get("q") ?? "");

  useEffect(() => {
    const q = searchParams.get("q") ?? "";
    setSearch(q);
  }, [searchParams]);

  const filters: Record<string, string> = {};
  if (statusFilter) filters.status = statusFilter;
  if (buildingFilter) filters.building = buildingFilter;

  const { data: units, isLoading } = useUnits(filters);
  const { data: summary } = useUnitStatusSummary(buildingFilter || undefined);
  const { data: buildings } = useBuildings();

  const filtered = (units ?? []).filter((u) =>
    search ? `${u.label} ${u.building_name}`.toLowerCase().includes(search.toLowerCase()) : true
  );

  const occupancyPct = summary && summary.total > 0
    ? Math.round(((summary.occupied_paid + summary.occupied_partial + summary.occupied_unpaid + summary.arrears) / summary.total) * 100)
    : 0;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Inventory"
        title="Units"
        description="Every unit across your buildings, colour-coded by rent status."
      />

      {/* Summary strip */}
      {summary ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {[
            { label: "Total", value: summary.total, tone: "peri" as const },
            { label: "Vacant", value: summary.vacant, tone: "vacant" as const },
            { label: "Paid", value: summary.occupied_paid, tone: "paid" as const },
            { label: "Partial", value: summary.occupied_partial, tone: "partial" as const },
            { label: "Unpaid", value: summary.occupied_unpaid, tone: "unpaid" as const },
            { label: "Arrears", value: summary.arrears, tone: "unpaid" as const },
          ].map((c) => (
            <Card key={c.label} variant="glass" padding="sm" className="text-center">
              <p className="text-[10px] font-medium uppercase tracking-[0.14em] text-ink-500">
                {c.label}
              </p>
              <p className="mt-1 font-display text-2xl font-semibold text-ink-900 tabular-nums">
                {c.value}
              </p>
            </Card>
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-16" />
          ))}
        </div>
      )}

      {summary && (
        <Card variant="glass" padding="md" className="relative overflow-hidden">
          <div className="pointer-events-none absolute -right-20 -top-20 h-64 w-64 rounded-full bg-sage-400/20 blur-3xl" />
          <div className="relative flex flex-wrap items-center gap-6">
            <div>
              <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-ink-500">
                Occupancy rate
              </p>
              <p className="mt-1 font-display text-4xl font-semibold text-ink-900">{occupancyPct}%</p>
            </div>
            <div className="flex-1 min-w-[200px]">
              <div className="flex h-3 w-full overflow-hidden rounded-full bg-ink-100/60">
                <div
                  className="bg-status-paid transition-all"
                  style={{ width: `${(summary.occupied_paid / Math.max(summary.total, 1)) * 100}%` }}
                />
                <div
                  className="bg-status-partial transition-all"
                  style={{ width: `${(summary.occupied_partial / Math.max(summary.total, 1)) * 100}%` }}
                />
                <div
                  className="bg-status-unpaid transition-all"
                  style={{ width: `${((summary.occupied_unpaid + summary.arrears) / Math.max(summary.total, 1)) * 100}%` }}
                />
              </div>
              <div className="mt-2 flex flex-wrap gap-3 text-[11px]">
                <span className="flex items-center gap-1.5">
                  <span className="h-1.5 w-1.5 rounded-full bg-status-paid" />
                  <span className="text-ink-500">Paid</span>
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="h-1.5 w-1.5 rounded-full bg-status-partial" />
                  <span className="text-ink-500">Partial</span>
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="h-1.5 w-1.5 rounded-full bg-status-unpaid" />
                  <span className="text-ink-500">Unpaid / Arrears</span>
                </span>
              </div>
            </div>
          </div>
        </Card>
      )}

      {/* Filters */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="flex-1">
          <Input
            leftIcon={<Search className="h-4 w-4" />}
            placeholder="Search units by label or building…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <select
          value={buildingFilter}
          onChange={(e) => setBuildingFilter(e.target.value)}
          className="glass rounded-md px-3 py-2.5 text-sm text-ink-900 focus:outline-none"
        >
          <option value="">All buildings</option>
          {buildings?.map((b) => (
            <option key={b.id} value={b.id}>
              {b.name}
            </option>
          ))}
        </select>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {STATUS_FILTERS.map((f) => {
          const active = statusFilter === f.value;
          return (
            <button
              key={f.value || "all"}
              onClick={() => setStatusFilter(f.value)}
              className={cn(
                "rounded-full px-3 py-1.5 text-xs font-medium transition-all",
                active
                  ? "bg-ink-900 text-canvas shadow-float dark:bg-ink-100 dark:text-canvas"
                  : "glass text-ink-700 hover:shadow-glass"
              )}
            >
              {f.label}
            </button>
          );
        })}
      </div>

      {/* Grid */}
      {isLoading ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-36" />
          ))}
        </div>
      ) : !filtered.length ? (
        <EmptyState
          icon={<Home className="h-5 w-5" />}
          title="No units match"
          description="Try adjusting the filter or search."
        />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {filtered.map((unit) => (
            <Card
              key={unit.id}
              variant="glass"
              padding="none"
              interactive
              className="relative overflow-hidden"
            >
              <span
                className={cn(
                  "absolute left-0 top-0 h-full w-1.5",
                  STATUS_RAIL[unit.status]
                )}
              />
              <div className="p-5 pl-6">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-[0.16em] text-ink-500">
                      <Home className="h-3 w-3" />
                      {unit.building_name}
                    </div>
                    <p className="mt-1 font-display text-xl font-semibold text-ink-900">
                      {unit.label}
                    </p>
                  </div>
                  <StatusBadge status={unit.status as UnitStatus} />
                </div>

                <div className="mt-4 flex items-end justify-between">
                  <div>
                    <p className="text-[10px] uppercase tracking-wider text-ink-400">Monthly rent</p>
                    <p className="font-display text-xl font-semibold text-ink-900 tabular-nums">
                      <span className="text-sm text-ink-500">KES </span>
                      {Number(unit.monthly_rent).toLocaleString()}
                    </p>
                  </div>
                  <Badge tone="neutral" className="capitalize">
                    {unit.unit_type.replace("_", " ")}
                  </Badge>
                </div>

                {unit.floor !== undefined && (
                  <p className="mt-3 flex items-center gap-1 text-[11px] text-ink-500">
                    <Sparkles className="h-3 w-3" />
                    Floor {unit.floor}
                  </p>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
