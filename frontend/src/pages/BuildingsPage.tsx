/**
 * BuildingsPage — full building management:
 * • Multi-step wizard to create a building + define its units
 * • Building cards with unit grid preview, occupancy bar
 * • Inline edit (name / address / floors) and delete per building
 */
import { zodResolver } from "@hookform/resolvers/zod";
import {
  Building2,
  ChevronDown,
  ChevronUp,
  Pencil,
  Plus,
  Trash2,
  X,
  Check,
  AlertTriangle,
} from "lucide-react";
import { useState } from "react";
import { useFieldArray, useForm } from "react-hook-form";
import toast from "react-hot-toast";
import { z } from "zod";

import StatusBadge from "@/components/StatusBadge";
import {
  useBulkCreateUnits,
  useBuilding,
  useBuildings,
  useCreateBuilding,
  useDeleteBuilding,
  useUpdateBuilding,
} from "@/hooks/useBuildings";
import type { Building, Unit, UnitType } from "@/lib/types";

// ─── Zod schemas ────────────────────────────────────────────────────────────

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

const unitsSchema = z.object({
  units: z.array(unitRowSchema).min(1),
});

type BuildingFormValues = z.infer<typeof buildingSchema>;
type UnitsFormValues = z.infer<typeof unitsSchema>;

// ─── Constants ──────────────────────────────────────────────────────────────

const UNIT_TYPES = [
  { value: "single", label: "Single Room" },
  { value: "double", label: "Double Room" },
  { value: "bedsitter", label: "Bedsitter" },
  { value: "1br", label: "1 Bedroom" },
  { value: "2br", label: "2 Bedroom" },
  { value: "3br", label: "3 Bedroom" },
  { value: "shop", label: "Shop / Commercial" },
];

// ─── Step 1: Building details form ──────────────────────────────────────────

function StepBuilding({
  onNext,
}: {
  onNext: (values: BuildingFormValues) => void;
}) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<BuildingFormValues>({
    resolver: zodResolver(buildingSchema),
    defaultValues: { name: "", address: "", total_floors: 1, notes: "", unit_count: 1 },
  });

  return (
    <form onSubmit={handleSubmit(onNext)} className="space-y-4">
      <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">
        Step 1 of 3 — Building details
      </p>
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className="label">Building name *</label>
          <input {...register("name")} className="input" placeholder="e.g. Maple Court" />
          {errors.name && <p className="err">{errors.name.message}</p>}
        </div>
        <div>
          <label className="label">Address</label>
          <input {...register("address")} className="input" placeholder="Street, Estate, Town" />
        </div>
        <div>
          <label className="label">Total floors *</label>
          <input type="number" min={1} {...register("total_floors")} className="input" />
          {errors.total_floors && <p className="err">{errors.total_floors.message}</p>}
        </div>
        <div>
          <label className="label">Number of units *</label>
          <input type="number" min={1} max={200} {...register("unit_count")} className="input" />
          {errors.unit_count && <p className="err">{errors.unit_count.message}</p>}
        </div>
      </div>
      <div>
        <label className="label">Notes</label>
        <textarea {...register("notes")} rows={2} className="input" />
      </div>
      <div className="flex justify-end">
        <button type="submit" className="btn-primary">
          Next: Configure units →
        </button>
      </div>
    </form>
  );
}

// ─── Step 2: Configure each unit ─────────────────────────────────────────────

function StepUnits({
  count,
  floors,
  onBack,
  onNext,
}: {
  count: number;
  floors: number;
  onBack: () => void;
  onNext: (values: UnitsFormValues) => void;
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
    defaultValues: {
      units: Array.from({ length: count }, (_, i) => defaultUnit(i)),
    },
  });

  const { fields } = useFieldArray({ control, name: "units" });

  return (
    <form onSubmit={handleSubmit(onNext)} className="space-y-4">
      <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">
        Step 2 of 3 — Configure {count} unit{count !== 1 ? "s" : ""}
      </p>
      <div className="max-h-[380px] overflow-y-auto space-y-3 pr-1">
        {fields.map((field, i) => (
          <div key={field.id} className="rounded-lg border border-slate-200 bg-slate-50 p-3">
            <p className="mb-2 text-xs font-semibold text-slate-600">Unit {i + 1}</p>
            <div className="grid gap-3 sm:grid-cols-4">
              <div>
                <label className="label">Label *</label>
                <input {...register(`units.${i}.label`)} className="input" />
                {errors.units?.[i]?.label && (
                  <p className="err">{errors.units[i]?.label?.message}</p>
                )}
              </div>
              <div>
                <label className="label">Floor</label>
                <input
                  type="number"
                  min={0}
                  max={floors}
                  {...register(`units.${i}.floor`)}
                  className="input"
                />
              </div>
              <div>
                <label className="label">Type</label>
                <select {...register(`units.${i}.unit_type`)} className="input">
                  {UNIT_TYPES.map((t) => (
                    <option key={t.value} value={t.value}>{t.label}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="label">Monthly rent (KES) *</label>
                <input
                  type="number"
                  min={1}
                  {...register(`units.${i}.monthly_rent`)}
                  className="input"
                />
                {errors.units?.[i]?.monthly_rent && (
                  <p className="err">{errors.units[i]?.monthly_rent?.message}</p>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
      <div className="flex justify-between">
        <button type="button" onClick={onBack} className="btn-ghost">← Building details</button>
        <button type="submit" className="btn-primary">Next: Preview →</button>
      </div>
    </form>
  );
}

// ─── Step 3: Preview ─────────────────────────────────────────────────────────

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
      <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">
        Step 3 of 3 — Preview & confirm
      </p>
      <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 space-y-1">
        <p className="font-semibold text-slate-900">{building.name}</p>
        {building.address && <p className="text-sm text-slate-500">{building.address}</p>}
        <p className="text-sm text-slate-500">{building.total_floors} floor(s) · {units.length} unit(s)</p>
        {building.notes && <p className="text-sm text-slate-400 italic">{building.notes}</p>}
      </div>
      <div className="max-h-[280px] overflow-y-auto rounded-lg border border-slate-200 divide-y divide-slate-100">
        {units.map((u, i) => (
          <div key={i} className="flex items-center justify-between px-4 py-2.5 text-sm">
            <span className="font-medium text-slate-800">{u.label}</span>
            <span className="text-slate-500">
              Floor {u.floor} · {UNIT_TYPES.find((t) => t.value === u.unit_type)?.label}
            </span>
            <span className="font-semibold text-slate-900">
              KES {Number(u.monthly_rent).toLocaleString()}
            </span>
          </div>
        ))}
      </div>
      <div className="flex justify-between">
        <button type="button" onClick={onBack} className="btn-ghost">← Back</button>
        <button onClick={onConfirm} disabled={isPending} className="btn-primary">
          {isPending ? "Saving…" : <><Check className="h-4 w-4 mr-1 inline" /> Confirm & save</>}
        </button>
      </div>
    </div>
  );
}

// ─── Wizard modal ────────────────────────────────────────────────────────────

function CreateBuildingWizard({ onClose }: { onClose: () => void }) {
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [buildingData, setBuildingData] = useState<BuildingFormValues | null>(null);
  const [unitsData, setUnitsData] = useState<UnitsFormValues["units"] | null>(null);
  const [createdBuildingId, setCreatedBuildingId] = useState<number | null>(null);

  const createBuilding = useCreateBuilding();

  // We call bulk-create-units after building is created.
  // buildingId is available after step 1 completes (server-side).
  const bulkCreate = useBulkCreateUnits(createdBuildingId ?? 0);

  const handleBuildingNext = async (values: BuildingFormValues) => {
    // Create the building on the server now so we have an ID for units.
    try {
      const created = await createBuilding.mutateAsync({
        name: values.name,
        address: values.address || "",
        total_floors: values.total_floors,
        notes: values.notes || "",
      });
      setCreatedBuildingId(created.id);
      setBuildingData(values);
      setStep(2);
    } catch {
      toast.error("Failed to create building. Is the name unique?");
    }
  };

  const handleUnitsNext = (values: UnitsFormValues) => {
    setUnitsData(values.units);
    setStep(3);
  };  const handleConfirm = async () => {
    if (!unitsData || !createdBuildingId) return;
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
      toast.error("Units failed to save. The building was created — you can add units from the edit view.");
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm">
      <div className="relative w-full max-w-2xl rounded-2xl bg-white shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-100 px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-slate-900">
              <Building2 className="h-5 w-5 text-white" />
            </div>
            <h2 className="text-base font-bold text-slate-900">Add Building</h2>
          </div>
          {/* Step pills */}
          <div className="flex items-center gap-1.5">
            {[1, 2, 3].map((s) => (
              <div
                key={s}
                className={`h-2 rounded-full transition-all ${
                  s === step ? "w-6 bg-slate-900" : s < step ? "w-2 bg-slate-400" : "w-2 bg-slate-200"
                }`}
              />
            ))}
          </div>
          <button onClick={onClose} className="rounded-lg p-1.5 text-slate-400 hover:text-slate-700 hover:bg-slate-100">
            <X className="h-5 w-5" />
          </button>
        </div>
        {/* Body */}
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

// ─── Edit building inline form ────────────────────────────────────────────────

const editSchema = z.object({
  name: z.string().min(1, "Name is required"),
  address: z.string().optional(),
  total_floors: z.coerce.number().int().min(1),
  notes: z.string().optional(),
});
type EditFormValues = z.infer<typeof editSchema>;

function EditBuildingForm({
  building,
  onDone,
}: {
  building: Building;
  onDone: () => void;
}) {
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
    <form onSubmit={handleSubmit(onSubmit)} className="mt-4 space-y-3 border-t border-slate-100 pt-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className="label">Name *</label>
          <input {...register("name")} className="input" />
          {errors.name && <p className="err">{errors.name.message}</p>}
        </div>
        <div>
          <label className="label">Address</label>
          <input {...register("address")} className="input" />
        </div>
        <div>
          <label className="label">Total floors *</label>
          <input type="number" min={1} {...register("total_floors")} className="input" />
        </div>
        <div>
          <label className="label">Notes</label>
          <input {...register("notes")} className="input" />
        </div>
      </div>
      <div className="flex justify-end gap-2">
        <button type="button" onClick={onDone} className="btn-ghost text-sm">Cancel</button>
        <button type="submit" disabled={updateBuilding.isPending} className="btn-primary text-sm">
          {updateBuilding.isPending ? "Saving…" : "Save changes"}
        </button>
      </div>
    </form>
  );
}

// ─── Delete confirmation ──────────────────────────────────────────────────────

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
      toast.error("Failed to delete building. It may have active tenants.");
    }
  };

  return (
    <div className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3 space-y-2 border-t-0">
      <div className="flex items-center gap-2 text-red-700">
        <AlertTriangle className="h-4 w-4 flex-shrink-0" />
        <p className="text-sm font-medium">
          Delete <span className="font-bold">{building.name}</span>? This will remove all units. This cannot be undone.
        </p>
      </div>
      <div className="flex justify-end gap-2">
        <button onClick={onCancel} className="btn-ghost text-sm">Cancel</button>
        <button
          onClick={handleDelete}
          disabled={deleteBuilding.isPending}
          className="rounded-lg bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-60"
        >
          {deleteBuilding.isPending ? "Deleting…" : "Yes, delete"}
        </button>
      </div>
    </div>
  );
}

// ─── Building card ────────────────────────────────────────────────────────────

function BuildingCard({ building }: { building: Building & { units?: Unit[] } }) {
  const [expanded, setExpanded] = useState(false);
  const [mode, setMode] = useState<"view" | "edit" | "delete">("view");

  // Lazy-fetch full building detail (with units) only when expanded.
  const { data: detail, isFetching: loadingUnits } = useBuilding(
    expanded ? building.id : ""
  );

  const occupied = building.occupied_count ?? 0;
  const total = building.unit_count ?? 0;
  const vacant = total - occupied;
  const occupancyPct = total > 0 ? Math.round((occupied / total) * 100) : 0;

  return (
    <div className="rounded-2xl border border-slate-200 bg-white shadow-sm transition-shadow hover:shadow-md overflow-hidden">
      {/* Card header */}
      <div className="p-5">
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-3 min-w-0">
            <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl bg-slate-900">
              <Building2 className="h-5 w-5 text-white" />
            </div>
            <div className="min-w-0">
              <h3 className="truncate text-sm font-bold text-slate-900">{building.name}</h3>
              {building.address && (
                <p className="truncate text-xs text-slate-500">{building.address}</p>
              )}
            </div>
          </div>
          {/* Action buttons */}
          <div className="flex flex-shrink-0 items-center gap-1">
            <button
              onClick={() => setMode(mode === "edit" ? "view" : "edit")}
              className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
              title="Edit building"
            >
              <Pencil className="h-4 w-4" />
            </button>
            <button
              onClick={() => setMode(mode === "delete" ? "view" : "delete")}
              className="rounded-lg p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-600"
              title="Delete building"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Stats row */}
        <div className="mt-4 grid grid-cols-3 gap-2 text-center">
          <div className="rounded-lg bg-slate-50 py-2">
            <p className="text-lg font-bold text-slate-900">{total}</p>
            <p className="text-[11px] text-slate-500">Total</p>
          </div>
          <div className="rounded-lg bg-emerald-50 py-2">
            <p className="text-lg font-bold text-emerald-700">{occupied}</p>
            <p className="text-[11px] text-emerald-600">Occupied</p>
          </div>
          <div className="rounded-lg bg-slate-50 py-2">
            <p className="text-lg font-bold text-slate-400">{vacant}</p>
            <p className="text-[11px] text-slate-400">Vacant</p>
          </div>
        </div>

        {/* Occupancy bar */}
        <div className="mt-3">
          <div className="flex justify-between text-[11px] text-slate-400 mb-1">
            <span>Occupancy</span>
            <span>{occupancyPct}%</span>
          </div>
          <div className="h-1.5 w-full rounded-full bg-slate-100">
            <div
              className="h-1.5 rounded-full bg-emerald-500 transition-all"
              style={{ width: `${occupancyPct}%` }}
            />
          </div>
        </div>

        <p className="mt-2 text-[11px] text-slate-400">{building.total_floors} floor(s)</p>
      </div>

      {/* Edit / Delete panels */}
      {mode === "edit" && (
        <div className="px-5 pb-5">
          <EditBuildingForm building={building} onDone={() => setMode("view")} />
        </div>
      )}
      {mode === "delete" && (
        <div className="px-5 pb-5">
          <DeleteConfirm
            building={building}
            onCancel={() => setMode("view")}
            onDeleted={() => setMode("view")}
          />
        </div>
      )}

      {/* Unit grid toggle */}
      {total > 0 && (
        <>
          <button
            onClick={() => setExpanded((v) => !v)}
            className="flex w-full items-center justify-between border-t border-slate-100 px-5 py-2.5 text-xs font-medium text-slate-500 hover:bg-slate-50"
          >
            <span>{expanded ? "Hide" : "Show"} units</span>
            {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          </button>
          {expanded && (
            <div className="border-t border-slate-100 px-5 pb-5 pt-3">
              {loadingUnits ? (
                <p className="text-xs text-slate-400 py-2">Loading units…</p>
              ) : (
                <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
                  {(detail?.units ?? []).map((u) => (
                    <div
                      key={u.id}
                      className="flex items-center justify-between rounded-lg border border-slate-100 bg-slate-50 px-3 py-2"
                    >
                      <div>
                        <p className="text-xs font-semibold text-slate-800">{u.label}</p>
                        <p className="text-[10px] text-slate-400">
                          KES {Number(u.monthly_rent).toLocaleString()}
                        </p>
                      </div>
                      <StatusBadge status={u.status} size="sm" />
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function BuildingsPage() {
  const { data: buildings, isLoading } = useBuildings();
  const [showWizard, setShowWizard] = useState(false);

  return (
    <>
      {/* Global utility classes — scoped via a wrapping div */}
      <style>{`
        .label { display:block; font-size:0.75rem; font-weight:500; color:#475569; margin-bottom:0.2rem; }
        .input { display:block; width:100%; border-radius:0.5rem; border:1px solid #cbd5e1;
                 padding:0.45rem 0.65rem; font-size:0.875rem; outline:none; background:white; }
        .input:focus { border-color:#94a3b8; box-shadow:0 0 0 2px rgba(148,163,184,.25); }
        .err { margin-top:0.2rem; font-size:0.7rem; color:#dc2626; }
        .btn-primary { display:inline-flex; align-items:center; border-radius:0.5rem;
                       background:#0f172a; padding:0.5rem 1rem; font-size:0.875rem;
                       font-weight:500; color:#fff; }
        .btn-primary:hover:not(:disabled) { background:#1e293b; }
        .btn-primary:disabled { opacity:0.6; cursor:not-allowed; }
        .btn-ghost { display:inline-flex; align-items:center; border-radius:0.5rem;
                     border:1px solid #e2e8f0; padding:0.5rem 1rem; font-size:0.875rem;
                     font-weight:500; color:#475569; background:white; }
        .btn-ghost:hover { background:#f8fafc; }
      `}</style>

      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold text-slate-900">Buildings</h2>
            <p className="text-sm text-slate-500">
              {buildings?.length ?? 0} building{buildings?.length !== 1 ? "s" : ""}
            </p>
          </div>
          <button
            onClick={() => setShowWizard(true)}
            className="inline-flex items-center gap-2 rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-slate-800"
          >
            <Plus className="h-4 w-4" />
            Add Building
          </button>
        </div>

        {/* Cards grid */}
        {isLoading ? (
          <div className="py-16 text-center text-slate-400">Loading buildings…</div>
        ) : !buildings?.length ? (
          <div className="flex flex-col items-center justify-center rounded-2xl border-2 border-dashed border-slate-200 py-20 text-center">
            <Building2 className="mx-auto mb-3 h-10 w-10 text-slate-300" />
            <p className="text-sm font-medium text-slate-500">No buildings yet</p>
            <p className="mt-1 text-xs text-slate-400">Click "Add Building" to get started</p>
          </div>
        ) : (
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {buildings.map((b) => (
              <BuildingCard key={b.id} building={b as Building & { units?: Unit[] }} />
            ))}
          </div>
        )}
      </div>

      {/* Wizard modal */}
      {showWizard && <CreateBuildingWizard onClose={() => setShowWizard(false)} />}
    </>
  );
}
