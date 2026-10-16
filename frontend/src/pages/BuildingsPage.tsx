import {
  AlertTriangle,
  ArrowUpRight,
  Building2,
  ChevronDown,
  ChevronUp,
  Pencil,
  Plus,
  Search,
  Trash2,
  Wrench,
} from "lucide-react";
import { useEffect, useId, useState } from "react";
import toast from "react-hot-toast";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import StatusBadge from "@/components/StatusBadge";
import {
  Badge,
  Button,
  Card,
  DatePicker,
  EmptyState,
  ErrorState,
  Input,
  Modal,
  PageHeader,
  Skeleton,
} from "@/components/ui";
import {
  useBuilding,
  useBuildingPhotoSrc,
  useBuildings,
  useDeleteBuilding,
} from "@/hooks/useBuildings";
import { getErrorMessage } from "@/lib/apiError";
import { cn } from "@/lib/cn";
import { toDayFirst, todayIso } from "@/lib/dates";
import type { Building, Unit } from "@/lib/types";
import { api } from "@/lib/api";
import { useQueryClient } from "@tanstack/react-query";

// ─── Shared field helpers ───────────────────────────────────────────────────
const inputCls =
  "w-full rounded-md bg-surface-raised hairline px-3 py-2.5 text-sm text-ink-900 placeholder:text-ink-400 focus:outline-none focus:ring-2 focus:ring-sage-500/40";

// ─── Adjust Rent Modal ──────────────────────────────────────────────────────
function AdjustRentModal({
  unit,
  onClose,
}: {
  unit: Unit;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [rent, setRent] = useState(String(unit.monthly_rent));
  const [descriptor, setDescriptor] = useState(
    (unit as unknown as { statement_descriptor?: string }).statement_descriptor ?? "",
  );
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    if (!rent || isNaN(Number(rent))) return;
    setSaving(true);
    try {
      await api.patch(`/units/${unit.id}/`, {
        monthly_rent: rent,
        statement_descriptor: descriptor,
      });
      qc.invalidateQueries({ queryKey: ["buildings"] });
      qc.invalidateQueries({ queryKey: ["units"] });
      toast.success(`Unit ${unit.label} updated`);
      onClose();
    } catch {
      toast.error("Failed to update unit");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      size="sm"
      eyebrow="Edit rent"
      title={`Unit ${unit.label}`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button onClick={handleSave} loading={saving}>Save</Button>
        </>
      }
    >
      <p className="-mt-1 mb-4 text-sm text-ink-500">
        Current rent: <span className="font-medium text-ink-900">KES {Number(unit.monthly_rent).toLocaleString()}</span>
      </p>

      <label className="mb-1 block text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">
        Monthly rent (KES)
      </label>
      <input
        type="number"
        min={0}
        step={100}
        value={rent}
        onChange={(e) => setRent(e.target.value)}
        className={inputCls}
        autoFocus
      />

      <label className="mb-1 mt-4 block text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">
        Statement descriptor
      </label>
      <input
        type="text"
        value={descriptor}
        onChange={(e) => setDescriptor(e.target.value)}
        placeholder="e.g. Unit G05 — Hospital"
        className={inputCls}
      />
      <p className="mt-1.5 text-[11px] text-ink-500">
        Right-hand cell on the rent statement. Leave blank to auto-build from unit label and building name.
      </p>
    </Modal>
  );
}

// ─── Maintenance Log Modal ───────────────────────────────────────────────────
function MaintenanceModal({
  unit,
  onClose,
}: {
  unit: Unit;
  onClose: () => void;
}) {

  const qc = useQueryClient();
  const [form, setForm] = useState({
    description: "",
    cost: "",
    reported_date: todayIso(),
    notes: "",
  });
  const [saving, setSaving] = useState(false);
  const [requests, setRequests] = useState<Record<string, unknown>[]>([]);
  const [loadingRequests, setLoadingRequests] = useState(true);

  useEffect(() => {
    api.get(`/maintenance/?unit=${unit.id}`)
      .then((r) => setRequests(r.data as Record<string, unknown>[]))
      .catch(() => {})
      .finally(() => setLoadingRequests(false));
  }, [unit.id]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      await api.post("/maintenance/", {
        unit: unit.id,
        description: form.description,
        cost: form.cost || "0",
        reported_date: form.reported_date,
        notes: form.notes,
        status: "open",
      });
      toast.success("Maintenance request logged. Cost added to Expenses.");
      qc.invalidateQueries({ queryKey: ["buildings"] });
      qc.invalidateQueries({ queryKey: ["expenses"] });
      onClose();
    } catch {
      toast.error("Failed to log maintenance request");
    } finally {
      setSaving(false);
    }
  };

  const formId = "maintenance-form";

  return (
    <Modal
      open
      onClose={onClose}
      size="xl"
      eyebrow={`Unit ${unit.label}`}
      title="Log maintenance"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" form={formId} loading={saving}>
            <Wrench className="h-4 w-4" /> Log maintenance
          </Button>
        </>
      }
    >
      <form id={formId} onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="mb-1 block text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">
            What needs to be done? *
          </label>
          <textarea
            required
            rows={3}
            value={form.description}
            onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
            className={inputCls}
            placeholder="e.g. Fix leaking pipe in bathroom, replace broken window…"
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="mb-1 block text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">
              Cost (KES)
            </label>
            <input
              type="number"
              min={0}
              step={100}
              value={form.cost}
              onChange={(e) => setForm((f) => ({ ...f, cost: e.target.value }))}
              className={inputCls}
              placeholder="0"
            />
            <p className="mt-1 text-[10px] text-ink-500">Will auto-sync to Expenses tab</p>
          </div>
          <DatePicker
            label="Reported date *"
            required
            value={form.reported_date}
            onChange={(e) => setForm((f) => ({ ...f, reported_date: e.target.value }))}
          />
        </div>
        <div>
          <label className="mb-1 block text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">
            Additional notes
          </label>
          <input
            value={form.notes}
            onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
            className={inputCls}
            placeholder="Any additional details…"
          />
        </div>
      </form>

      {/* Existing requests for this unit */}
      {loadingRequests ? (
        <p className="mt-6 text-xs text-ink-500">Loading maintenance history…</p>
      ) : requests.length > 0 ? (
        <div className="mt-6 border-t border-ink-100 pt-4 dark:border-ink-700">
          <p className="mb-2 text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">
            Maintenance history
          </p>
          <ul className="space-y-2">
            {requests.map((r: Record<string, unknown>, i: number) => (
              <li key={i} className="rounded-md bg-surface-sunk px-3 py-2 text-xs">
                <div className="flex items-start justify-between gap-2">
                  <p className="font-medium text-ink-900 dark:text-white">{r.description as string}</p>
                  <span className={cn(
                    "shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium tracking-wide",
                    r.status === "done" ? "bg-sage-500/12 text-sage-700" :
                    r.status === "in_progress" ? "bg-peri-500/12 text-peri-600" :
                    "bg-ochre-500/12 text-ochre-700"
                  )}>
                    {String(r.status).replace("_", " ")}
                  </span>
                </div>
                <p className="mt-1 text-ink-500">
                  KES {Number(r.cost).toLocaleString()} · {toDayFirst(String(r.reported_date))}
                </p>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </Modal>
  );
}

// ─── Delete Building ─────────────────────────────────────────────────────────
function DeleteBuildingModal({ building, onClose }: { building: Building; onClose: () => void }) {
  const deleteBuilding = useDeleteBuilding();
  const units = building.unit_count ?? 0;
  const occupied = building.occupied_count ?? 0;
  const handleDelete = async () => {
    try {
      await deleteBuilding.mutateAsync(building.id);
      toast.success(`${building.name} deleted`);
      onClose();
    } catch (e) {
      toast.error(getErrorMessage(e, "The building could not be deleted. Move its tenants out first."));
    }
  };
  return (
    <Modal
      open
      onClose={onClose}
      size="sm"
      eyebrow="Delete building"
      title={building.name}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Keep building</Button>
          <Button variant="danger" onClick={handleDelete} loading={deleteBuilding.isPending} disabled={occupied > 0}>
            <Trash2 className="h-4 w-4" /> Delete permanently
          </Button>
        </>
      }
    >
      <div className="flex items-start gap-3 rounded-md bg-danger-soft p-3 text-sm text-danger">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        {occupied > 0 ? (
          <p>
            {occupied} of its {units} units {occupied === 1 ? "is" : "are"} let. Move those tenants out
            before deleting the building.
          </p>
        ) : (
          <p>
            This removes the building and its {units} unit{units !== 1 ? "s" : ""} for good. It cannot be undone.
          </p>
        )}
      </div>
    </Modal>
  );
}

// ─── Building card ──────────────────────────────────────────────────────────
function BuildingCard({ building }: { building: Building & { units?: Unit[] } }) {
  const [expanded, setExpanded] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [rentUnitModal, setRentUnitModal] = useState<Unit | null>(null);
  const [maintenanceUnit, setMaintenanceUnit] = useState<Unit | null>(null);
  const { data: detail, isFetching: loadingUnits } = useBuilding(expanded ? building.id : "");
  const unitsPanelId = useId();
  const photoSrc = useBuildingPhotoSrc(building);

  const occupied = building.occupied_count ?? 0;
  const total = building.unit_count ?? 0;
  const vacant = total - occupied;
  const occupancyPct = total > 0 ? Math.round((occupied / total) * 100) : 0;

  return (
    <>
      <Card variant="glass" padding="none" className="group flex flex-col overflow-hidden">
        {/* Cover: the photo opens the property; nothing floats on it but the name. */}
        <Link
          to={`/buildings/${building.id}`}
          className="relative block h-40 w-full overflow-hidden focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
        >
          <img
            src={photoSrc}
            alt=""
            loading="lazy"
            className="h-full w-full object-cover transition-transform duration-500 ease-out group-hover:scale-105"
          />
          <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-black/10 to-transparent" />
          <div className="absolute bottom-3 left-4 right-4 flex items-end justify-between gap-2">
            <div className="min-w-0">
              <p className="truncate font-display text-lg font-semibold text-white">{building.name}</p>
              {building.address && <p className="truncate text-xs text-white/80">{building.address}</p>}
            </div>
            <Badge
              tone={occupancyPct >= 80 ? "paid" : occupancyPct >= 50 ? "partial" : "unpaid"}
              withDot
              className="shrink-0 backdrop-blur"
            >
              {occupancyPct}% let
            </Badge>
          </div>
        </Link>

        {/* Figures */}
        <div className="px-5 pt-4">
          <dl className="grid grid-cols-3 gap-2">
            <div>
              <dt className="text-[10px] uppercase tracking-wider text-content-muted">Let</dt>
              <dd className="font-display text-xl font-semibold tabular-nums text-success">{occupied}</dd>
            </div>
            <div>
              <dt className="text-[10px] uppercase tracking-wider text-content-muted">Vacant</dt>
              <dd className="font-display text-xl font-semibold tabular-nums text-content">{vacant}</dd>
            </div>
            <div>
              <dt className="text-[10px] uppercase tracking-wider text-content-muted">Units</dt>
              <dd className="font-display text-xl font-semibold tabular-nums text-content">{total}</dd>
            </div>
          </dl>
          <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-surface-sunk" aria-hidden>
            <div className="h-full bg-success" style={{ width: `${occupancyPct}%` }} />
          </div>
          <p className="mt-2 text-[11px] text-content-muted">
            {building.total_floors} floor{building.total_floors !== 1 ? "s" : ""}
          </p>
        </div>

        {/* Unit rents and repairs, edited without leaving the page. */}
        {total > 0 && (
          <div className="mt-4 border-t border-hairline">
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              aria-expanded={expanded}
              aria-controls={unitsPanelId}
              className="flex w-full items-center justify-between px-5 py-3 text-xs font-medium text-content-secondary transition-colors hover:bg-hover"
            >
              <span>Edit unit rents &amp; repairs</span>
              {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
            </button>
            {expanded && (
              <div id={unitsPanelId} className="max-h-80 overflow-y-auto border-t border-hairline px-5 py-1">
                {loadingUnits ? (
                  <div className="space-y-2 py-2">
                    {Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-10" />)}
                  </div>
                ) : (
                  <ul className="divide-y divide-hairline">
                    {(detail?.units ?? []).map((u) => (
                      <li key={u.id} className="flex items-center justify-between gap-2 py-2 text-xs">
                        <div className="min-w-0">
                          <p className="flex items-center gap-2 font-medium text-content">
                            <span className="truncate">{u.label}</span>
                            <StatusBadge status={u.status} />
                          </p>
                          <p className="text-[11px] tabular-nums text-content-muted">
                            KES {Number(u.monthly_rent).toLocaleString()} a month
                          </p>
                        </div>
                        <div className="flex shrink-0 items-center gap-1">
                          <button
                            type="button"
                            onClick={() => setRentUnitModal(u)}
                            aria-label={`Edit rent for ${u.label}`}
                            className="inline-flex h-7 items-center gap-1 rounded-md px-2 font-medium text-success transition-colors hover:bg-success-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-success"
                          >
                            <Pencil className="h-3 w-3" /> Rent
                          </button>
                          <button
                            type="button"
                            onClick={() => setMaintenanceUnit(u)}
                            aria-label={`Log a repair for ${u.label}`}
                            className="inline-flex h-7 items-center gap-1 rounded-md px-2 font-medium text-content-secondary transition-colors hover:bg-hover hover:text-content focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                          >
                            <Wrench className="h-3 w-3" /> Repair
                          </button>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>
        )}

        {/* Footer: go somewhere on the left, change the building on the right. */}
        <div className="mt-auto flex items-center justify-between gap-2 border-t border-hairline px-5 py-3">
          <Link
            to={`/units?building=${building.id}`}
            className="inline-flex items-center gap-1 rounded-md text-xs font-medium text-content-secondary transition-colors hover:text-content focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            View units <ArrowUpRight className="h-3.5 w-3.5" />
          </Link>
          <div className="flex items-center gap-1.5">
            <Link
              to={`/buildings/${building.id}/edit`}
              aria-label={`Edit ${building.name}`}
              className="inline-flex h-8 items-center gap-1.5 rounded-md bg-success-soft px-3 text-xs font-semibold text-success transition-colors hover:bg-success hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-success"
            >
              <Pencil className="h-3.5 w-3.5" /> Edit
            </Link>
            <button
              type="button"
              onClick={() => setDeleting(true)}
              aria-label={`Delete ${building.name}`}
              className="inline-flex h-8 items-center gap-1.5 rounded-md bg-danger-soft px-3 text-xs font-semibold text-danger transition-colors hover:bg-danger hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-danger"
            >
              <Trash2 className="h-3.5 w-3.5" /> Delete
            </button>
          </div>
        </div>
      </Card>

      {deleting && <DeleteBuildingModal building={building} onClose={() => setDeleting(false)} />}
      {rentUnitModal && <AdjustRentModal unit={rentUnitModal} onClose={() => setRentUnitModal(null)} />}
      {maintenanceUnit && <MaintenanceModal unit={maintenanceUnit} onClose={() => setMaintenanceUnit(null)} />}
    </>
  );
}

// ─── Main ───────────────────────────────────────────────────────────────────
export default function BuildingsPage() {
  const { data: buildings, isLoading, isError, refetch } = useBuildings();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [search, setSearch] = useState(searchParams.get("q") ?? "");

  useEffect(() => {
    const q = searchParams.get("q") ?? "";
    setSearch(q);
  }, [searchParams]);

  const filtered = (buildings ?? []).filter((b) =>
    search ? `${b.name} ${b.address}`.toLowerCase().includes(search.toLowerCase()) : true
  );

  return (
    <>
      <div className="space-y-6">
        <PageHeader
          eyebrow="Portfolio"
          title="Buildings"
          description={`${buildings?.length ?? 0} ${
            (buildings?.length ?? 0) === 1 ? "property" : "properties"
          } under management.`}
          actions={
            <Button onClick={() => navigate("/buildings/new")}>
              <Plus className="h-4 w-4" />
              Add Building
            </Button>
          }
        />

        <div className="max-w-md">
          <Input
            leftIcon={<Search className="h-4 w-4" />}
            placeholder="Search buildings…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        {isLoading ? (
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-80" />
            ))}
          </div>
        ) : isError ? (
          <Card variant="glass" padding="none" className="py-4">
            <ErrorState
              title="Buildings could not be loaded."
              description="Your properties did not come back. This is usually temporary."
              onRetry={() => void refetch()}
            />
          </Card>
        ) : !filtered.length ? (
          <Card variant="glass" padding="none" className="py-4">
            <EmptyState
              icon={<Building2 className="h-6 w-6" />}
              title="No buildings yet"
              description={
                search
                  ? "Try a different search term."
                  : "Click Add Building to register your first property."
              }
              action={
                !search ? (
                  <Button onClick={() => navigate("/buildings/new")}>
                    <Plus className="h-4 w-4" />
                    Add Building
                  </Button>
                ) : undefined
              }
            />
          </Card>
        ) : (
          <div className="grid items-start gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {filtered.map((b) => (
              <BuildingCard key={b.id} building={b as Building & { units?: Unit[] }} />
            ))}
          </div>
        )}
      </div>
    </>
  );
}
