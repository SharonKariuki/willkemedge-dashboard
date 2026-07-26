import { ChevronDown, Home, Search, User } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import StatusBadge from "@/components/StatusBadge";
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  Input,
  PageHeader,
  Skeleton,
} from "@/components/ui";
import { useBuildings } from "@/hooks/useBuildings";
import { useUnitStatusSummary, useUnits } from "@/hooks/useUnits";
import { cn } from "@/lib/cn";
import type { UnitStatus } from "@/lib/types";

const STATUS_FILTERS = [
  { value: "", label: "All statuses", tone: "neutral" as const },
  { value: "vacant", label: "Vacant", tone: "vacant" as const },
  { value: "occupied_paid", label: "Paid", tone: "paid" as const },
  { value: "occupied_partial", label: "Partial", tone: "partial" as const },
  { value: "occupied_unpaid", label: "Unpaid", tone: "unpaid" as const },
  { value: "arrears", label: "Arrears", tone: "unpaid" as const },
];

function FilterSelect({
  label, value, onChange, options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <div className="relative">
      <select
        aria-label={label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={cn(
          "h-full w-full appearance-none rounded-md border border-border bg-surface py-2.5 pl-3.5 pr-9 text-sm transition-colors",
          "focus:border-teal-600 focus:outline-none focus:ring-2 focus:ring-ring/25",
          value ? "font-medium text-content" : "text-content-muted",
        )}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
      <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-content-muted" />
    </div>
  );
}

const STATUS_RAIL: Record<UnitStatus, string> = {
  vacant: "bg-status-vacant",
  occupied_paid: "bg-status-paid",
  occupied_partial: "bg-status-partial",
  occupied_unpaid: "bg-status-unpaid",
  arrears: "bg-status-unpaid",
};

export default function UnitsPage() {
  const navigate = useNavigate();
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

  const { data: units, isLoading, isError, refetch } = useUnits(filters);
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
      <PageHeader title="Units" />

      {/* Summary strip */}
      {summary ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-7">
          {/* Total — gradient hero, matching the dashboard "Collected" card */}
          <div className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-navy-600 via-navy-800 to-navy-900 px-3 py-2 text-center text-white shadow-lg">
            <div aria-hidden className="pointer-events-none absolute -right-8 -top-10 h-24 w-24 rounded-full bg-teal-500/25 blur-2xl" />
            <p className="relative text-[9px] font-medium uppercase tracking-[0.14em] text-white/60">
              Total
            </p>
            <p className="relative mt-0.5 font-display text-lg font-semibold tabular-nums">
              {summary.total}
            </p>
          </div>
          {/* Status counts + occupancy — glass cards, value coloured by status */}
          {[
            { label: "Vacant", value: summary.vacant, valueCls: "text-ink-600 dark:text-ink-300" },
            { label: "Paid", value: summary.occupied_paid, valueCls: "text-status-paid" },
            { label: "Partial", value: summary.occupied_partial, valueCls: "text-status-partial" },
            { label: "Unpaid", value: summary.occupied_unpaid, valueCls: "text-status-unpaid" },
            { label: "Arrears", value: summary.arrears, valueCls: "text-status-unpaid" },
            { label: "Occupancy", value: `${occupancyPct}%`, valueCls: "text-teal-700 dark:text-teal-400" },
          ].map((c) => (
            <Card key={c.label} variant="glass" padding="none" className="px-3 py-2 text-center">
              <p className="text-[9px] font-medium uppercase tracking-[0.14em] text-ink-500">
                {c.label}
              </p>
              <p className={cn("mt-0.5 font-display text-lg font-semibold tabular-nums", c.valueCls)}>
                {c.value}
              </p>
            </Card>
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-7">
          {Array.from({ length: 7 }).map((_, i) => (
            <Skeleton key={i} className="h-12" />
          ))}
        </div>
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
        <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap">
          <FilterSelect
            label="Filter by status"
            value={statusFilter}
            onChange={setStatusFilter}
            options={STATUS_FILTERS.map((f) => ({ value: f.value, label: f.label }))}
          />
          <FilterSelect
            label="Filter by building"
            value={buildingFilter}
            onChange={setBuildingFilter}
            options={[
              { value: "", label: "All buildings" },
              ...(buildings ?? []).map((b) => ({ value: String(b.id), label: b.name })),
            ]}
          />
        </div>
      </div>

      {/* Grid */}
      {isLoading ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-36" />
          ))}
        </div>
      ) : isError ? (
        <ErrorState
          title="Units could not be loaded."
          description="Your unit inventory did not come back. This is usually temporary."
          onRetry={() => void refetch()}
        />
      ) : !filtered.length ? (
        <EmptyState
          icon={<Home className="h-5 w-5" />}
          title="No units match"
          description="Try adjusting the filter or search."
        />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {filtered.map((unit) => {
            const hasTenant = unit.current_tenant_id != null;
            return (
            <Card
              key={unit.id}
              variant="glass"
              padding="none"
              interactive={hasTenant}
              onClick={
                hasTenant
                  ? () => navigate(`/tenants/${unit.current_tenant_id}`)
                  : undefined
              }
              role={hasTenant ? "button" : undefined}
              title={hasTenant ? `View ${unit.current_tenant_name}` : undefined}
              className={cn(
                "relative overflow-hidden",
                hasTenant && "cursor-pointer"
              )}
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

                {unit.current_tenant_name && (
                  <div className="mt-3 flex items-center gap-2 text-[11px] text-ink-500">
                    <span className="flex min-w-0 items-center gap-1 text-ink-600">
                      <User className="h-3 w-3 shrink-0" />
                      <span className="truncate">{unit.current_tenant_name}</span>
                    </span>
                  </div>
                )}
              </div>
            </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
