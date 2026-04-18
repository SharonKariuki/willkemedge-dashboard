import { zodResolver } from "@hookform/resolvers/zod";
import {
  AlertTriangle,
  Building2,
  Check,
  ChevronDown,
  ChevronUp,
  Pencil,
  Plus,
  Search,
  Trash2,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useFieldArray, useForm } from "react-hook-form";
import toast from "react-hot-toast";
import { useSearchParams } from "react-router-dom";
import { z } from "zod";

import StatusBadge from "@/components/StatusBadge";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Input,
  PageHeader,
  Skeleton,
} from "@/components/ui";
import {
  useBulkCreateUnits,
  useBuilding,
  useBuildings,
  useCreateBuilding,
  useDeleteBuilding,
  useUpdateBuilding,
} from "@/hooks/useBuildings";
import { cn } from "@/lib/cn";
import { propertyImage } from "@/lib/images";
import type { Building, Unit, UnitType } from "@/lib/types";

// ─── Schemas ────────────────────────────────────────────────────────────────
const buildingSchema = z.object({
  name: z.string().min(1, "Name is required"),
  address: z.string().optional(),
  total_floors: z.coerce.number().int().min(1, "At least 1 floor"),
  notes: z.string().optional(),
  unit_count: z.coerce.number().int().min(1, "At least 1 unit"),
});

const unitRowSchema = z.object({
  label: z.string().min(1, "Label required"),
  floor: z.coerce.number().int().min(0),
  unit_type: z.string().min(1),
  monthly_rent: z.coerce.number().min(1, "Rent required"),
  notes: z.string().optional(),
});

const unitsSchema = z.object({ units: z.array(unitRowSchema).min(1) });

type BuildingFormValues = z.infer<typeof buildingSchema>;
type UnitsFormValues = z.infer<typeof unitsSchema>;

const UNIT_TYPES = [
  { value: "single", label: "Single Room" },
  { value: "double", label: "Double Room" },
  { value: "bedsitter", label: "Bedsitter" },
  { value: "1br", label: "1 Bedroom" },
  { value: "2br", label: "2 Bedroom" },
  { value: "3br", label: "3 Bedroom" },
  { value: "shop", label: "Shop / Commercial" },
];

// ─── Shared field helpers ───────────────────────────────────────────────────
function Field({
  label,
  error,
  children,
}: {
  label: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="mb-1 block text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">
        {label}
      </label>
      {children}
      {error && <p className="mt-1 text-[11px] text-status-unpaid">{error}</p>}
    </div>
  );
}

const inputCls =
  "w-full rounded-md bg-surface-raised hairline px-3 py-2.5 text-sm text-ink-900 placeholder:text-ink-400 focus:outline-none focus:ring-2 focus:ring-sage-500/40";

// ─── Wizard steps ───────────────────────────────────────────────────────────
function StepBuilding({ onNext }: { onNext: (v: BuildingFormValues) => void }) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<BuildingFormValues>({
    resolver: zodResolver(buildingSchema),
    defaultValues: { name: "", address: "", total_floors: 1, notes: "", unit_count: 1 },
  });
  return (
    <form onSubmit={handleSubmit(onNext)} className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Building name *" error={errors.name?.message}>
          <input {...register("name")} className={inputCls} placeholder="e.g. Maple Court" />
        </Field>
        <Field label="Address">
          <input {...register("address")} className={inputCls} placeholder="Street, Estate, Town" />
        </Field>
        <Field label="Total floors *" error={errors.total_floors?.message}>
          <input type="number" min={1} {...register("total_floors")} className={inputCls} />
        </Field>
        <Field label="Number of units *" error={errors.unit_count?.message}>
          <input type="number" min={1} max={200} {...register("unit_count")} className={inputCls} />
        </Field>
      </div>
      <Field label="Notes">
        <textarea {...register("notes")} rows={2} className={inputCls} />
      </Field>
      <div className="flex justify-end">
        <Button type="submit">Next: Configure units →</Button>
      </div>
    </form>
  );
}

function StepUnits({
  count,
  floors,
  onBack,
  onNext,
}: {
  count: number;
  floors: number;
  onBack: () => void;
  onNext: (v: UnitsFormValues) => void;
}) {
  const defaultUnit = (i: number) => ({
    label: `Unit ${i + 1}`,
    floor: 0,
    unit_type: "single",
    monthly_rent: 0,
    notes: "",
  });
  const {
    register,
    handleSubmit,
    control,
    formState: { errors },
  } = useForm<UnitsFormValues>({
    resolver: zodResolver(unitsSchema),
    defaultValues: { units: Array.from({ length: count }, (_, i) => defaultUnit(i)) },
  });
  const { fields } = useFieldArray({ control, name: "units" });

  return (
    <form onSubmit={handleSubmit(onNext)} className="space-y-4">
      <div className="max-h-[420px] space-y-3 overflow-y-auto pr-1">
        {fields.map((field, i) => (
          <div key={field.id} className="neu-sm p-4">
            <p className="mb-3 text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">
              Unit {i + 1}
            </p>
            <div className="grid gap-3 sm:grid-cols-4">
              <Field label="Label *" error={errors.units?.[i]?.label?.message}>
                <input {...register(`units.${i}.label`)} className={inputCls} />
              </Field>
              <Field label="Floor">
                <input
                  type="number"
                  min={0}
                  max={floors}
                  {...register(`units.${i}.floor`)}
                  className={inputCls}
                />
              </Field>
              <Field label="Type">
                <select {...register(`units.${i}.unit_type`)} className={inputCls}>
                  {UNIT_TYPES.map((t) => (
                    <option key={t.value} value={t.value}>
                      {t.label}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Rent (KES) *" error={errors.units?.[i]?.monthly_rent?.message}>
                <input type="number" min={1} {...register(`units.${i}.monthly_rent`)} className={inputCls} />
              </Field>
            </div>
          </div>
        ))}
      </div>
      <div className="flex justify-between">
        <Button type="button" variant="ghost" onClick={onBack}>
          ← Back
        </Button>
        <Button type="submit">Preview →</Button>
      </div>
    </form>
  );
}

function StepPreview({
  building,
  units,
  onBack,
  onConfirm,
  isPending,
}: {
  building: BuildingFormValues;
  units: UnitsFormValues["units"];
  onBack: () => void;
  onConfirm: () => void;
  isPending: boolean;
}) {
  return (
    <div className="space-y-4">
      <Card variant="neu-sm" padding="md">
        <p className="font-display text-lg font-semibold text-ink-900">{building.name}</p>
        {building.address && <p className="text-sm text-ink-500">{building.address}</p>}
        <p className="mt-1 text-xs text-ink-500">
          {building.total_floors} floor(s) · {units.length} unit(s)
        </p>
      </Card>
      <div className="max-h-[320px] overflow-y-auto rounded-md hairline">
        {units.map((u, i) => (
          <div
            key={i}
            className="flex items-center justify-between border-b border-ink-200/40 px-4 py-2.5 text-sm last:border-b-0"
          >
            <span className="font-medium text-ink-900">{u.label}</span>
            <span className="text-xs text-ink-500">
              Floor {u.floor} · {UNIT_TYPES.find((t) => t.value === u.unit_type)?.label}
            </span>
            <span className="font-semibold text-ink-900 tabular-nums">
              KES {Number(u.monthly_rent).toLocaleString()}
            </span>
          </div>
        ))}
      </div>
      <div className="flex justify-between">
        <Button type="button" variant="ghost" onClick={onBack}>
          ← Back
        </Button>
        <Button onClick={onConfirm} loading={isPending}>
          <Check className="h-4 w-4" />
          Confirm & save
        </Button>
      </div>
    </div>
  );
}

function CreateBuildingWizard({ onClose }: { onClose: () => void }) {
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [buildingData, setBuildingData] = useState<BuildingFormValues | null>(null);
  const [unitsData, setUnitsData] = useState<UnitsFormValues["units"] | null>(null);
  const [createdId, setCreatedId] = useState<number | null>(null);

  const createBuilding = useCreateBuilding();
  const bulkCreate = useBulkCreateUnits(createdId ?? 0);

  const handleBuildingNext = async (values: BuildingFormValues) => {
    try {
      const created = await createBuilding.mutateAsync({
        name: values.name,
        address: values.address || "",
        total_floors: values.total_floors,
        notes: values.notes || "",
      });
      setCreatedId(created.id);
      setBuildingData(values);
      setStep(2);
    } catch {
      toast.error("Failed to create building. Is the name unique?");
    }
  };

  const handleUnitsNext = (values: UnitsFormValues) => {
    setUnitsData(values.units);
    setStep(3);
  };

  const handleConfirm = async () => {
    if (!unitsData || !createdId) return;
    try {
      await bulkCreate.mutateAsync(
        unitsData.map((u) => ({
          label: u.label,
          floor: u.floor,
          unit_type: u.unit_type as UnitType,
          monthly_rent: String(u.monthly_rent),
          notes: u.notes || "",
        }))
      );
      toast.success(`Building created with ${unitsData.length} unit(s)`);
      onClose();
    } catch {
      toast.error("Units failed to save. Building was created — add units from the edit view.");
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div
        className="absolute inset-0 bg-ink-900/30 backdrop-blur-md"
        onClick={onClose}
      />
      <div className="glass-strong relative w-full max-w-2xl overflow-hidden rounded-xl animate-fade-up">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-ink-200/40 px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-md bg-ink-900 text-white shadow-glass">
              <Building2 className="h-5 w-5" />
            </div>
            <div>
              <p className="font-display text-base font-semibold text-ink-900">Add Building</p>
              <p className="text-[11px] uppercase tracking-[0.14em] text-ink-500">
                Step {step} of 3
              </p>
            </div>
          </div>
          <div className="flex items-center gap-1.5">
            {[1, 2, 3].map((s) => (
              <div
                key={s}
                className={cn(
                  "h-1.5 rounded-full transition-all",
                  s === step ? "w-8 bg-sage-500" : s < step ? "w-4 bg-sage-400/60" : "w-4 bg-ink-200"
                )}
              />
            ))}
          </div>
          <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="Close">
            <X className="h-4 w-4" />
          </Button>
        </div>
        <div className="p-6">
          {step === 1 && <StepBuilding onNext={handleBuildingNext} />}
          {step === 2 && buildingData && (
            <StepUnits
              count={buildingData.unit_count}
              floors={buildingData.total_floors}
              onBack={() => setStep(1)}
              onNext={handleUnitsNext}
            />
          )}
          {step === 3 && buildingData && unitsData && (
            <StepPreview
              building={buildingData}
              units={unitsData}
              onBack={() => setStep(2)}
              onConfirm={handleConfirm}
              isPending={bulkCreate.isPending}
            />
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Edit / Delete inline ───────────────────────────────────────────────────
const editSchema = z.object({
  name: z.string().min(1),
  address: z.string().optional(),
  total_floors: z.coerce.number().int().min(1),
  notes: z.string().optional(),
});
type EditFormValues = z.infer<typeof editSchema>;

function EditBuildingForm({ building, onDone }: { building: Building; onDone: () => void }) {
  const updateBuilding = useUpdateBuilding(building.id);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<EditFormValues>({
    resolver: zodResolver(editSchema),
    defaultValues: {
      name: building.name,
      address: building.address,
      total_floors: building.total_floors,
      notes: building.notes,
    },
  });
  const onSubmit = async (values: EditFormValues) => {
    try {
      await updateBuilding.mutateAsync(values);
      toast.success("Building updated");
      onDone();
    } catch {
      toast.error("Failed to update building");
    }
  };
  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-3 border-t border-ink-200/40 pt-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Name *" error={errors.name?.message}>
          <input {...register("name")} className={inputCls} />
        </Field>
        <Field label="Address">
          <input {...register("address")} className={inputCls} />
        </Field>
        <Field label="Total floors *">
          <input type="number" min={1} {...register("total_floors")} className={inputCls} />
        </Field>
        <Field label="Notes">
          <input {...register("notes")} className={inputCls} />
        </Field>
      </div>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" size="sm" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" size="sm" loading={updateBuilding.isPending}>
          Save
        </Button>
      </div>
    </form>
  );
}

function DeleteConfirm({
  building,
  onCancel,
  onDeleted,
}: {
  building: Building;
  onCancel: () => void;
  onDeleted: () => void;
}) {
  const deleteBuilding = useDeleteBuilding();
  const handleDelete = async () => {
    try {
      await deleteBuilding.mutateAsync(building.id);
      toast.success(`"${building.name}" deleted`);
      onDeleted();
    } catch {
      toast.error("Failed to delete. Check for active tenants.");
    }
  };
  return (
    <div className="space-y-3 rounded-md bg-status-unpaid/8 p-4 border border-status-unpaid/20">
      <div className="flex items-start gap-2 text-status-unpaid">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        <p className="text-sm">
          Delete <strong>{building.name}</strong>? This removes all its units permanently.
        </p>
      </div>
      <div className="flex justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={onCancel}>
          Cancel
        </Button>
        <Button variant="danger" size="sm" loading={deleteBuilding.isPending} onClick={handleDelete}>
          Yes, delete
        </Button>
      </div>
    </div>
  );
}

// ─── Building card ──────────────────────────────────────────────────────────
function BuildingCard({ building }: { building: Building & { units?: Unit[] } }) {
  const [expanded, setExpanded] = useState(false);
  const [mode, setMode] = useState<"view" | "edit" | "delete">("view");
  const { data: detail, isFetching: loadingUnits } = useBuilding(expanded ? building.id : "");

  const occupied = building.occupied_count ?? 0;
  const total = building.unit_count ?? 0;
  const vacant = total - occupied;
  const occupancyPct = total > 0 ? Math.round((occupied / total) * 100) : 0;

  return (
    <Card variant="glass" padding="none" className="group overflow-hidden">
      {/* Cover image */}
      <div className="relative h-40 w-full overflow-hidden">
        <img
          src={propertyImage(building.id ?? building.name, "md")}
          alt={building.name}
          loading="lazy"
          className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-105"
        />
        <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-black/10 to-transparent" />
        <div className="absolute bottom-3 left-4 right-4 flex items-end justify-between gap-2">
          <div className="min-w-0">
            <p className="truncate font-display text-lg font-semibold text-white">{building.name}</p>
            {building.address && (
              <p className="truncate text-xs text-white/80">{building.address}</p>
            )}
          </div>
          <Badge
            tone={occupancyPct >= 80 ? "sage" : occupancyPct >= 50 ? "ochre" : "coral"}
            withDot
            className="shrink-0 backdrop-blur"
          >
            {occupancyPct}%
          </Badge>
        </div>
        <div className="absolute right-3 top-3 flex gap-1">
          <button
            onClick={() => setMode(mode === "edit" ? "view" : "edit")}
            className="glass flex h-8 w-8 items-center justify-center rounded-md text-white"
            aria-label="Edit"
          >
            <Pencil className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={() => setMode(mode === "delete" ? "view" : "delete")}
            className="glass flex h-8 w-8 items-center justify-center rounded-md text-white hover:text-status-unpaid"
            aria-label="Delete"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* Body */}
      <div className="p-5">
        <div className="grid grid-cols-3 gap-2 text-center">
          <div className="rounded-md bg-white/40 py-2 dark:bg-white/5">
            <p className="font-display text-xl font-semibold text-ink-900 tabular-nums">{total}</p>
            <p className="text-[10px] uppercase tracking-wider text-ink-500">Total</p>
          </div>
          <div className="rounded-md bg-status-paid/8 py-2">
            <p className="font-display text-xl font-semibold text-status-paid tabular-nums">
              {occupied}
            </p>
            <p className="text-[10px] uppercase tracking-wider text-ink-500">Occupied</p>
          </div>
          <div className="rounded-md bg-white/40 py-2 dark:bg-white/5">
            <p className="font-display text-xl font-semibold text-ink-400 tabular-nums">{vacant}</p>
            <p className="text-[10px] uppercase tracking-wider text-ink-500">Vacant</p>
          </div>
        </div>

        <div className="mt-4">
          <div className="flex h-1.5 w-full overflow-hidden rounded-full bg-ink-100/60">
            <div
              className="bg-gradient-to-r from-sage-400 to-sage-600 transition-all"
              style={{ width: `${occupancyPct}%` }}
            />
          </div>
          <div className="mt-2 flex justify-between text-[11px] text-ink-500">
            <span>{building.total_floors} floor(s)</span>
            <span>Occupancy</span>
          </div>
        </div>

        {mode === "edit" && (
          <div className="mt-4">
            <EditBuildingForm building={building} onDone={() => setMode("view")} />
          </div>
        )}
        {mode === "delete" && (
          <div className="mt-4">
            <DeleteConfirm
              building={building}
              onCancel={() => setMode("view")}
              onDeleted={() => setMode("view")}
            />
          </div>
        )}
      </div>

      {total > 0 && (
        <>
          <button
            onClick={() => setExpanded((v) => !v)}
            className="flex w-full items-center justify-between border-t border-ink-200/40 px-5 py-3 text-xs font-medium text-ink-500 hover:bg-white/30 dark:hover:bg-white/5"
          >
            <span>{expanded ? "Hide units" : "Show units"}</span>
            {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          </button>
          {expanded && (
            <div className="border-t border-ink-200/40 p-4">
              {loadingUnits ? (
                <div className="space-y-2">
                  {Array.from({ length: 3 }).map((_, i) => (
                    <Skeleton key={i} className="h-10" />
                  ))}
                </div>
              ) : (
                <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                  {(detail?.units ?? []).map((u) => (
                    <div
                      key={u.id}
                      className="flex items-center justify-between rounded-md bg-white/40 px-3 py-2 text-xs dark:bg-white/5"
                    >
                      <div className="min-w-0">
                        <p className="truncate font-medium text-ink-900">{u.label}</p>
                        <p className="text-[11px] text-ink-500 tabular-nums">
                          KES {Number(u.monthly_rent).toLocaleString()}
                        </p>
                      </div>
                      <StatusBadge status={u.status} />
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </Card>
  );
}

// ─── Main ───────────────────────────────────────────────────────────────────
export default function BuildingsPage() {
  const { data: buildings, isLoading } = useBuildings();
  const [searchParams] = useSearchParams();
  const [showWizard, setShowWizard] = useState(false);
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
            <Button onClick={() => setShowWizard(true)}>
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
                  <Button onClick={() => setShowWizard(true)}>
                    <Plus className="h-4 w-4" />
                    Add Building
                  </Button>
                ) : undefined
              }
            />
          </Card>
        ) : (
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {filtered.map((b) => (
              <BuildingCard key={b.id} building={b as Building & { units?: Unit[] }} />
            ))}
          </div>
        )}
      </div>
      {showWizard && <CreateBuildingWizard onClose={() => setShowWizard(false)} />}
    </>
  );
}
