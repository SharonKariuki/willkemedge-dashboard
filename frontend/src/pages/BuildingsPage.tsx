import { zodResolver } from "@hookform/resolvers/zod";
import {
  AlertTriangle,
  ArrowUpRight,
  Building2,
  Check,
  ChevronDown,
  ChevronUp,
  Pencil,
  Plus,
  Search,
  Trash2,
  Wrench,
} from "lucide-react";
import { cloneElement, isValidElement, useEffect, useId, useState } from "react";
import { useFieldArray, useForm } from "react-hook-form";
import toast from "react-hot-toast";
import { Link, useSearchParams } from "react-router-dom";
import { z } from "zod";

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
  useBulkCreateUnits,
  useBuilding,
  useBuildings,
  useCreateBuilding,
  useDeleteBuilding,
  useUpdateBuilding,
} from "@/hooks/useBuildings";
import { getErrorMessage } from "@/lib/apiError";
import { cn } from "@/lib/cn";
import { propertyImage } from "@/lib/images";
import type { Building, Unit, UnitType } from "@/lib/types";
import { api } from "@/lib/api";
import { useQueryClient } from "@tanstack/react-query";

// ─── Schemas ────────────────────────────────────────────────────────────────
const buildingSchema = z.object({
  name: z.string().min(1, "Name is required"),
  address: z.string().optional(),
  total_floors: z.coerce.number().int().min(1, "At least 1 floor"),
  notes: z.string().optional(),
  unit_count: z.coerce.number().int().min(1, "At least 1 unit"),
  building_type: z.enum(["RESIDENTIAL", "BUSINESS"]),
});

const unitRowSchema = z.object({
  label: z.string().min(1, "Label required"),
  floor: z.coerce.number().int().min(0),
  unit_type: z.string().min(1),
  // No .default() here: it makes the schema's input and output types diverge,
  // which broke the zodResolver typing (previously suppressed with `as any`).
  // The form always supplies a value via defaultUnit().
  classification: z.string().min(1),
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
  className,
}: {
  label: string;
  error?: string;
  children: React.ReactNode;
  className?: string;
}) {
  const id = useId();
  const control = isValidElement(children)
    ? cloneElement(children as React.ReactElement<{ id?: string }>, {
        id: (children as React.ReactElement<{ id?: string }>).props.id ?? id,
      })
    : children;
  return (
    <div className={className}>
      <label htmlFor={id} className="mb-1 block text-[11px] font-medium uppercase tracking-[0.14em] text-gray-600">
        {label}
      </label>
      {control}
      {error && <p className="mt-1 text-[11px] text-red-600">{error}</p>}
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
    watch,
    setValue,
    formState: { errors },
  } = useForm<BuildingFormValues>({

    resolver: zodResolver(buildingSchema),
    defaultValues: { name: "", address: "", total_floors: 1, notes: "", unit_count: 1, building_type: "RESIDENTIAL" },
  });

  const floors = watch("total_floors");
  const unitCount = watch("unit_count");
  const buildingType = watch("building_type");

  return (
    <form onSubmit={handleSubmit(onNext)} className="space-y-5">
      <div>
        <label className="mb-1.5 block text-[11px] font-medium uppercase tracking-[0.14em] text-gray-600">
          Building type *
        </label>
        <div className="grid grid-cols-2 gap-2">
          {([
            { value: "RESIDENTIAL", title: "Residential", desc: "Tenants are exempt from VAT" },
            { value: "BUSINESS", title: "Business / Commercial", desc: "Tenants pay 16% VAT on rent" },
          ] as const).map((opt) => {
            const active = buildingType === opt.value;
            return (
              <button
                key={opt.value}
                type="button"
                onClick={() => setValue("building_type", opt.value, { shouldDirty: true })}
                className={cn(
                  "rounded-lg border p-3 text-left transition-all",
                  active
                    ? "border-blue-500 bg-blue-50 ring-2 ring-blue-500/20"
                    : "border-gray-200 bg-white hover:border-gray-300"
                )}
              >
                <p className={cn("text-sm font-semibold", active ? "text-blue-700" : "text-gray-900")}>
                  {opt.title}
                </p>
                <p className="mt-0.5 text-[11px] text-gray-500">{opt.desc}</p>
              </button>
            );
          })}
        </div>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Building name *" error={errors.name?.message}>
          <input {...register("name")} className={inputCls} placeholder="e.g. Maple Court" />
        </Field>
        <Field label="Address">
          <input {...register("address")} className={inputCls} placeholder="Street, Estate, Town" />
        </Field>
        <Field label="Number of floors *" error={errors.total_floors?.message}>
          <input
            type="number"
            min={1}
            max={50}
            {...register("total_floors")}
            className={inputCls}
          />
          <p className="mt-1 text-[11px] text-gray-500">
            {floors > 1 ? `${floors} floors — units can be assigned to each floor` : "1 floor building"}
          </p>
        </Field>
        <Field label="Total units *" error={errors.unit_count?.message}>
          <input
            type="number"
            min={1}
            max={200}
            {...register("unit_count")}
            className={inputCls}
          />
          <p className="mt-1 text-[11px] text-gray-500">
            {unitCount} unit{unitCount !== 1 ? "s" : ""} — you'll configure each one next
          </p>
        </Field>
      </div>
      <Field label="Notes">
        <textarea {...register("notes")} rows={2} className={inputCls} placeholder="Any notes about this building…" />
      </Field>
      <div className="flex justify-end">
        <button
          type="submit"
          className="rounded-lg bg-gray-900 px-5 py-2.5 text-sm font-semibold text-white hover:bg-gray-800 transition-colors"
        >
          Next: Configure units →
        </button>
      </div>
    </form>
  );
}

function StepUnits({
  count,
  floors,
  buildingType,
  onBack,
  onNext,
}: {
  count: number;
  floors: number;
  buildingType: "RESIDENTIAL" | "BUSINESS";
  onBack: () => void;
  onNext: (v: UnitsFormValues) => void;
}) {
  const defaultUnit = (i: number) => ({
    label: `Unit ${i + 1}`,
    floor: Math.min(i, floors - 1),
    unit_type: buildingType === "BUSINESS" ? "shop" : "single",
    classification: buildingType,
    monthly_rent: 0,
    notes: "",
  });

  const {
    register,
    handleSubmit,
    control,
    watch,
    formState: { errors },
  } = useForm<UnitsFormValues>({
    resolver: zodResolver(unitsSchema),
    defaultValues: { units: Array.from({ length: count }, (_, i) => defaultUnit(i)) },
  });
  const { fields, append, remove } = useFieldArray({ control, name: "units" });

  return (
    <form onSubmit={handleSubmit(onNext)} className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-gray-600">Configure each unit — label, floor, type, and monthly rent.</p>
        <button
          type="button"
          onClick={() => append(defaultUnit(fields.length))}
          className="flex items-center gap-1.5 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 transition-colors"
        >
          <Plus className="h-3.5 w-3.5" /> Add unit
        </button>
      </div>
      <div className="max-h-[460px] space-y-6 overflow-y-auto pr-1">
        {Array.from({ length: floors }).map((_, floorIdx) => {
          const floorUnits = fields.map((f, i) => ({ ...f, index: i })).filter(u => watch(`units.${u.index}.floor`) === floorIdx);
          if (floorUnits.length === 0 && floorIdx > 0) return null; // Only show floor if it has units or is ground floor

          return (
            <div key={floorIdx} className="space-y-3">
              <div className="flex items-center gap-3">
                <div className="h-px flex-1 bg-gray-200" />
                <h4 className="text-[11px] font-bold uppercase tracking-widest text-gray-400">
                  {floorIdx === 0 ? "Ground Floor" : `Floor ${floorIdx}`}
                </h4>
                <div className="h-px flex-1 bg-gray-200" />
              </div>
              
              {floorUnits.map(({ id, index }) => (
                <div key={id} className="rounded-lg border border-gray-200 bg-gray-50 p-4 transition-all hover:border-blue-200 hover:bg-white">
                  <div className="mb-3 flex items-center justify-between">
                    <p className="text-[10px] font-bold uppercase tracking-wider text-blue-600">
                      Unit Config
                    </p>
                    {fields.length > 1 && (
                      <div className="flex items-center gap-1">
                        <button
                          type="button"
                          onClick={() => {
                            const u = watch(`units.${index}`);
                            append({ ...u, label: `${u.label} (copy)` });
                          }}
                          className="rounded p-1 text-gray-400 hover:text-blue-600 transition-colors"
                          title="Duplicate unit"
                        >
                          <Plus className="h-3.5 w-3.5" />
                        </button>
                        <button
                          type="button"
                          onClick={() => remove(index)}
                          className="rounded p-1 text-gray-400 hover:text-red-600 transition-colors"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    )}

                  </div>
                  <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                    <Field label="Label *" error={errors.units?.[index]?.label?.message}>
                      <input {...register(`units.${index}.label`)} className={inputCls} placeholder="e.g. A1, Shop 3" />
                    </Field>
                    <Field label="Floor">
                      <select {...register(`units.${index}.floor`)} className={inputCls}>
                        {Array.from({ length: floors }, (_, f) => (
                          <option key={f} value={f}>
                            {f === 0 ? "Ground Floor" : `Floor ${f}`}
                          </option>
                        ))}
                      </select>
                    </Field>
                    <Field label="Type">
                      <select {...register(`units.${index}.unit_type`)} className={inputCls}>
                        {UNIT_TYPES.map((t) => (
                          <option key={t.value} value={t.value}>
                            {t.label}
                          </option>
                        ))}
                      </select>
                    </Field>
                    <Field label="Rent (KES) *" error={errors.units?.[index]?.monthly_rent?.message}>
                      <input
                        type="number"
                        min={0}
                        step={100}
                        {...register(`units.${index}.monthly_rent`)}
                        className={inputCls}
                        placeholder="e.g. 15000"
                      />
                    </Field>
                  </div>
                </div>
              ))}
              
              <button
                type="button"
                onClick={() => append({ ...defaultUnit(fields.length), floor: floorIdx })}
                className="flex w-full items-center justify-center gap-1.5 rounded-lg border border-dashed border-gray-300 py-2.5 text-xs font-medium text-gray-500 hover:border-blue-400 hover:bg-blue-50 hover:text-blue-600 transition-all"
              >
                <Plus className="h-3.5 w-3.5" /> Add unit to {floorIdx === 0 ? "Ground Floor" : `Floor ${floorIdx}`}
              </button>
            </div>
          );
        })}
      </div>

      <div className="flex justify-between">
        <button
          type="button"
          onClick={onBack}
          className="rounded-lg border border-gray-300 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors"
        >
          ← Back
        </button>
        <button
          type="submit"
          className="rounded-lg bg-gray-900 px-5 py-2.5 text-sm font-semibold text-white hover:bg-gray-800 transition-colors"
        >
          Preview & confirm →
        </button>
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
  const totalRent = units.reduce((sum, u) => sum + Number(u.monthly_rent), 0);
  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-gray-200 bg-gray-50 p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="font-semibold text-gray-900">{building.name}</p>
            {building.address && <p className="text-sm text-gray-500 mt-0.5">{building.address}</p>}
          </div>
          <span className={cn(
            "shrink-0 rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider",
            building.building_type === "BUSINESS" ? "bg-blue-100 text-blue-700" : "bg-gray-200 text-gray-700"
          )}>
            {building.building_type === "BUSINESS" ? "Business · 16% VAT" : "Residential"}
          </span>
        </div>
        <div className="mt-2 flex gap-4 text-xs text-gray-500">
          <span>{building.total_floors} floor{building.total_floors !== 1 ? "s" : ""}</span>
          <span>{units.length} unit{units.length !== 1 ? "s" : ""}</span>
          <span className="font-medium text-gray-900">KES {totalRent.toLocaleString()} / month potential</span>
        </div>
      </div>
      <div className="max-h-[320px] overflow-y-auto rounded-lg border border-gray-200">
        <table className="w-full text-sm">
          <thead className="bg-gray-100">
            <tr>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-600">Label</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-600">Floor</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-600">Type</th>
              <th className="px-3 py-2 text-right text-xs font-medium text-gray-600">Rent (KES)</th>
            </tr>
          </thead>
          <tbody>
            {units.map((u, i) => (
              <tr key={i} className="border-t border-gray-100">
                <td className="px-3 py-2 font-medium text-gray-900">{u.label}</td>
                <td className="px-3 py-2 text-gray-500">{u.floor === 0 ? "Ground" : `Floor ${u.floor}`}</td>
                <td className="px-3 py-2 text-gray-500">
                  {UNIT_TYPES.find((t) => t.value === u.unit_type)?.label ?? u.unit_type}
                </td>
                <td className="px-3 py-2 text-right font-semibold text-gray-900">
                  {Number(u.monthly_rent).toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex justify-between">
        <button
          type="button"
          onClick={onBack}
          className="rounded-lg border border-gray-300 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors"
        >
          ← Back
        </button>
        <button
          type="button"
          onClick={onConfirm}
          disabled={isPending}
          className="flex items-center gap-2 rounded-lg bg-green-700 px-5 py-2.5 text-sm font-semibold text-white hover:bg-green-800 disabled:opacity-60 transition-colors"
        >
          <Check className="h-4 w-4" />
          {isPending ? "Saving…" : "Confirm & save building"}
        </button>
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
    } catch (e) {
      toast.error(getErrorMessage(e, "Failed to create building. The name must be unique."));
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
          classification: u.classification as import("@/lib/types").UnitClassification,
          monthly_rent: String(u.monthly_rent),
          notes: u.notes || "",
        }))
      );
      toast.success(`Building created with ${unitsData.length} unit${unitsData.length !== 1 ? "s" : ""}`);
      onClose();
    } catch (e) {
      toast.error(getErrorMessage(e, "Units failed to save. The building was created — add units from the edit view."));
    }
  };

  const stepLabels = ["Building info", "Configure units", "Review & confirm"];

  const headerSlot = (
    <div className="flex min-w-0 flex-1 items-center gap-3">
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-ochre-500/15 text-ochre-700">
        <Building2 className="h-4.5 w-4.5" />
      </div>
      <div className="min-w-0">
        <p className="text-[10px] font-medium uppercase tracking-[0.18em] text-ochre-600">
          New building
        </p>
        <p className="font-display text-lg font-semibold leading-tight text-ink-900 dark:text-white">
          {stepLabels[step - 1]}
        </p>
      </div>
    </div>
  );

  const stepIndicator = (
    <div className="hidden items-center gap-1.5 sm:flex" aria-label={`Step ${step} of 3`}>
      {[1, 2, 3].map((s) => (
        <div
          key={s}
          className={cn(
            "h-1 rounded-full transition-all",
            s === step ? "w-8 bg-ochre-500" : s < step ? "w-5 bg-ochre-500/50" : "w-5 bg-ink-200",
          )}
        />
      ))}
    </div>
  );

  return (
    <Modal open onClose={onClose} size="lg" header={headerSlot} headerActions={stepIndicator}>
      {step === 1 && <StepBuilding onNext={handleBuildingNext} />}
      {step === 2 && buildingData && (
        <StepUnits
          count={buildingData.unit_count}
          floors={buildingData.total_floors}
          buildingType={buildingData.building_type}
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
    </Modal>
  );
}

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
      eyebrow="Unit"
      title={`${unit.label}`}
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
    reported_date: new Date().toISOString().slice(0, 10),
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
                  KES {Number(r.cost).toLocaleString()} · {String(r.reported_date)}
                </p>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </Modal>
  );
}

// ─── Edit Building Form ──────────────────────────────────────────────────────
const editSchema = z.object({
  name: z.string().min(1),
  address: z.string().optional(),
  total_floors: z.coerce.number().int().min(1),
  notes: z.string().optional(),
});
type EditFormValues = z.infer<typeof editSchema>;

function EditBuildingForm({ building, onDone }: { building: Building; onDone: () => void }) {
  const updateBuilding = useUpdateBuilding(building.id);
  const { register, handleSubmit, formState: { errors } } = useForm<EditFormValues>({
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
    } catch (e) {
      toast.error(getErrorMessage(e, "Failed to update building"));
    }
  };
  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-3 border-t border-gray-200 pt-4">
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
        <button type="button" onClick={onDone} className="rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors">
          Cancel
        </button>
        <button type="submit" disabled={updateBuilding.isPending} className="rounded-lg bg-gray-900 px-3 py-2 text-sm font-semibold text-white hover:bg-gray-800 disabled:opacity-60 transition-colors">
          {updateBuilding.isPending ? "Saving…" : "Save changes"}
        </button>
      </div>
    </form>
  );
}

function DeleteConfirm({ building, onCancel, onDeleted }: { building: Building; onCancel: () => void; onDeleted: () => void }) {
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
    <div className="space-y-3 rounded-lg bg-red-50 p-4 border border-red-200 mt-4">
      <div className="flex items-start gap-2 text-red-700">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        <p className="text-sm">
          Delete <strong>{building.name}</strong>? This removes all its units permanently.
        </p>
      </div>
      <div className="flex justify-end gap-2">
        <button onClick={onCancel} className="rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors">
          Cancel
        </button>
        <button
          onClick={handleDelete}
          disabled={deleteBuilding.isPending}
          className="rounded-lg bg-red-600 px-3 py-2 text-sm font-semibold text-white hover:bg-red-700 disabled:opacity-60 transition-colors"
        >
          {deleteBuilding.isPending ? "Deleting…" : "Yes, delete"}
        </button>
      </div>
    </div>
  );
}

// ─── Building card ──────────────────────────────────────────────────────────
function BuildingCard({ building }: { building: Building & { units?: Unit[] } }) {
  const [expanded, setExpanded] = useState(false);
  const [mode, setMode] = useState<"view" | "edit" | "delete">("view");
  const [rentUnitModal, setRentUnitModal] = useState<Unit | null>(null);
  const [maintenanceUnit, setMaintenanceUnit] = useState<Unit | null>(null);
  const { data: detail, isFetching: loadingUnits } = useBuilding(expanded ? building.id : "");

  const occupied = building.occupied_count ?? 0;
  const total = building.unit_count ?? 0;
  const vacant = total - occupied;
  const occupancyPct = total > 0 ? Math.round((occupied / total) * 100) : 0;

  return (
    <>
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
              className="flex h-8 w-8 items-center justify-center rounded-md bg-white/90 text-gray-700 hover:bg-white shadow-sm"
              aria-label="Edit building"
            >
              <Pencil className="h-3.5 w-3.5" />
            </button>
            <button
              onClick={() => setMode(mode === "delete" ? "view" : "delete")}
              className="flex h-8 w-8 items-center justify-center rounded-md bg-white/90 text-gray-700 hover:bg-white hover:text-red-600 shadow-sm"
              aria-label="Delete building"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="p-5">
          <div className="grid grid-cols-3 gap-2 text-center">
            <div className="rounded-md bg-gray-50 py-2 border border-gray-100">
              <p className="font-display text-xl font-semibold text-gray-900 tabular-nums">{total}</p>
              <p className="text-[10px] uppercase tracking-wider text-gray-500">Total</p>
            </div>
            <div className="rounded-md bg-green-50 py-2 border border-green-100">
              <p className="font-display text-xl font-semibold text-green-700 tabular-nums">{occupied}</p>
              <p className="text-[10px] uppercase tracking-wider text-gray-500">Occupied</p>
            </div>
            <div className="rounded-md bg-gray-50 py-2 border border-gray-100">
              <p className="font-display text-xl font-semibold text-gray-400 tabular-nums">{vacant}</p>
              <p className="text-[10px] uppercase tracking-wider text-gray-500">Vacant</p>
            </div>
          </div>

          <div className="mt-4">
            <div className="flex h-1.5 w-full overflow-hidden rounded-full bg-gray-100">
              <div
                className="bg-gradient-to-r from-green-400 to-green-600 transition-all"
                style={{ width: `${occupancyPct}%` }}
              />
            </div>
            <div className="mt-2 flex justify-between text-[11px] text-gray-500">
              <span>{building.total_floors} floor{building.total_floors !== 1 ? "s" : ""}</span>
              <span>{occupancyPct}% Occupancy</span>
            </div>
          </div>

          {mode === "edit" && (
            <EditBuildingForm building={building} onDone={() => setMode("view")} />
          )}
          {mode === "delete" && (
            <DeleteConfirm
              building={building}
              onCancel={() => setMode("view")}
              onDeleted={() => setMode("view")}
            />
          )}

          <Link
            to={`/units?building=${building.id}`}
            className="mt-4 flex items-center justify-center gap-1 rounded-md bg-gray-900 py-2 text-xs font-medium text-white transition-colors hover:bg-gray-800"
          >
            View units
            <ArrowUpRight className="h-3.5 w-3.5" />
          </Link>
        </div>

        {total > 0 && (
          <>
            <button
              onClick={() => setExpanded((v) => !v)}
              className="flex w-full items-center justify-between border-t border-gray-200 px-5 py-3 text-xs font-medium text-gray-600 hover:bg-gray-50 transition-colors"
            >
              <span>{expanded ? "Hide units" : `Show ${total} unit${total !== 1 ? "s" : ""}`}</span>
              {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
            </button>
            {expanded && (
              <div className="border-t border-gray-200 p-4">
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
                        className="flex items-center justify-between rounded-md bg-gray-50 border border-gray-100 px-3 py-2 text-xs"
                      >
                        <div className="min-w-0">
                          <p className="truncate font-medium text-gray-900">{u.label}</p>
                          <p className="text-[11px] text-gray-500 tabular-nums">
                            KES {Number(u.monthly_rent).toLocaleString()}/mo
                          </p>
                        </div>
                        <div className="flex items-center gap-1.5 ml-2">
                          <StatusBadge status={u.status} />
                          <button
                            onClick={() => setRentUnitModal(u)}
                            title="Adjust rent"
                            className="rounded p-1 text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors"
                          >
                            <Pencil className="h-3 w-3" />
                          </button>
                          <button
                            onClick={() => setMaintenanceUnit(u)}
                            title="Log maintenance"
                            className="rounded p-1 text-gray-400 hover:text-orange-600 hover:bg-orange-50 transition-colors"
                          >
                            <Wrench className="h-3 w-3" />
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </Card>

      {rentUnitModal && (
        <AdjustRentModal unit={rentUnitModal} onClose={() => setRentUnitModal(null)} />
      )}
      {maintenanceUnit && (
        <MaintenanceModal unit={maintenanceUnit} onClose={() => setMaintenanceUnit(null)} />
      )}

    </>
  );
}

// ─── Main ───────────────────────────────────────────────────────────────────
export default function BuildingsPage() {
  const { data: buildings, isLoading, isError, refetch } = useBuildings();
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
