/**
 * AddBuildingPage — /buildings/new
 *
 * Adding a building gets a page rather than a dialog: a building can carry
 * dozens of units, and configuring them needs the room, an address that
 * survives a stray click, and the browser's back button.
 *
 * Three steps: the building, its units, then a review. Nothing is written
 * until the review is confirmed — the old dialog created the building as soon
 * as step one was done, so backing up and continuing tripped the unique-name
 * check, and abandoning the wizard left an empty building behind. Going back
 * keeps what was typed.
 */
import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowLeft, ArrowRight, Check, Copy, Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useFieldArray, useForm } from "react-hook-form";
import toast from "react-hot-toast";
import { Link, useNavigate } from "react-router-dom";
import { z } from "zod";

import { Button, Card, Table, TBody, TD, TH, THead, TR } from "@/components/ui";
import { PhotoPicker } from "@/features/buildings/PhotoPicker";
import { Field, inputCls } from "@/features/tenants/shared";
import { useCreateBuilding, useSetBuildingPhoto } from "@/hooks/useBuildings";
import { api } from "@/lib/api";
import { getErrorMessage } from "@/lib/apiError";
import { cn } from "@/lib/cn";
import { propertyImage } from "@/lib/images";
import { formatKES } from "@/lib/money";
import type { UnitClassification, UnitType } from "@/lib/types";
import { useQueryClient } from "@tanstack/react-query";

const BACK_TO = "/buildings";

const buildingSchema = z.object({
  name: z.string().trim().min(1, "Name is required"),
  address: z.string().optional(),
  total_floors: z.coerce.number().int().min(1, "At least 1 floor"),
  notes: z.string().optional(),
  unit_count: z.coerce.number().int().min(1, "At least 1 unit").max(200, "At most 200 units at once"),
  building_type: z.enum(["RESIDENTIAL", "BUSINESS"]),
});

const unitRowSchema = z.object({
  label: z.string().trim().min(1, "Label required"),
  floor: z.coerce.number().int().min(0),
  unit_type: z.string().min(1),
  // No .default() here: it makes the schema's input and output types diverge,
  // which breaks the zodResolver typing. The form always supplies a value.
  classification: z.string().min(1),
  monthly_rent: z.coerce.number().min(1, "Rent required"),
  notes: z.string().optional(),
});
const unitsSchema = z.object({ units: z.array(unitRowSchema).min(1, "Add at least one unit") });

type BuildingValues = z.infer<typeof buildingSchema>;
type UnitsValues = z.infer<typeof unitsSchema>;
type UnitRow = UnitsValues["units"][number];

const UNIT_TYPES = [
  { value: "single", label: "Single Room" },
  { value: "double", label: "Double Room" },
  { value: "bedsitter", label: "Bedsitter" },
  { value: "1br", label: "1 Bedroom" },
  { value: "2br", label: "2 Bedroom" },
  { value: "3br", label: "3 Bedroom" },
  { value: "shop", label: "Shop / Commercial" },
];

const STEPS = ["The building", "Its units", "Review"] as const;

const floorName = (f: number) => (f === 0 ? "Ground floor" : `Floor ${f}`);

// ─── Step 1 ──────────────────────────────────────────────────────────────────
type Photo = { blob: Blob; url: string } | null;

// Shown until a photo is chosen. The card picks its own stock picture once the
// building exists, so this one is only ever described as "a stock picture".
const NEW_BUILDING_PLACEHOLDER = propertyImage("new-building", "md");

function BuildingStep({
  initial, photo, onPhoto, onNext,
}: {
  initial: BuildingValues | null;
  photo: Photo;
  onPhoto: (blob: Blob | null) => void;
  onNext: (v: BuildingValues) => void;
}) {
  const { register, handleSubmit, watch, setValue, formState: { errors } } = useForm<BuildingValues>({
    resolver: zodResolver(buildingSchema),
    defaultValues: initial ?? {
      name: "", address: "", total_floors: 1, notes: "", unit_count: 1, building_type: "RESIDENTIAL",
    },
  });
  const buildingType = watch("building_type");
  const unitCount = Number(watch("unit_count")) || 0;

  return (
    <form onSubmit={handleSubmit(onNext)} className="space-y-6">
      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(16rem,22rem)]">
      <div className="min-w-0 space-y-5">
      <fieldset>
        <legend className="mb-1.5 block text-[11px] font-medium uppercase tracking-[0.14em] text-content-muted">
          Building type *
        </legend>
        <div className="grid gap-2 sm:grid-cols-2">
          {([
            { value: "RESIDENTIAL", title: "Residential", desc: "Tenants are exempt from VAT" },
            { value: "BUSINESS", title: "Business / Commercial", desc: "Tenants pay 16% VAT on rent" },
          ] as const).map((opt) => {
            const active = buildingType === opt.value;
            return (
              <button
                key={opt.value}
                type="button"
                aria-pressed={active}
                onClick={() => setValue("building_type", opt.value, { shouldDirty: true })}
                className={cn(
                  "rounded-md border p-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  active ? "border-teal-600 bg-teal-600/10" : "border-border bg-surface hover:border-border-strong",
                )}
              >
                <p className={cn("text-sm font-semibold", active ? "text-teal-800 dark:text-teal-400" : "text-content")}>
                  {opt.title}
                </p>
                <p className="mt-0.5 text-[11px] text-content-muted">{opt.desc}</p>
              </button>
            );
          })}
        </div>
      </fieldset>

      <div className="grid gap-4 md:grid-cols-2">
        <Field label="Building name *" error={errors.name?.message}>
          <input {...register("name")} className={inputCls} placeholder="e.g. Wilkem Edge Apartments - Donholm" />
        </Field>
        <Field label="Address">
          <input {...register("address")} className={inputCls} placeholder="Street, estate, town" />
        </Field>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <Field label="Number of floors *" error={errors.total_floors?.message} hint="Count the ground floor as one.">
          <input type="number" min={1} max={50} {...register("total_floors")} className={inputCls} />
        </Field>
        <Field
          label="Number of units *"
          error={errors.unit_count?.message}
          hint={`${unitCount} unit${unitCount === 1 ? "" : "s"}, set up one by one on the next step.`}
        >
          <input type="number" min={1} max={200} {...register("unit_count")} className={inputCls} />
        </Field>
      </div>
      <Field label="Notes">
        <textarea {...register("notes")} rows={4} className={inputCls} />
      </Field>
      </div>

      <PhotoPicker
        src={photo?.url ?? NEW_BUILDING_PLACEHOLDER}
        isPlaceholder={!photo}
        onPick={(blob) => onPhoto(blob)}
        onRemove={() => onPhoto(null)}
      />
      </div>

      <div className="flex justify-end gap-2 border-t border-hairline pt-4">
        <Link to={BACK_TO} className="inline-flex h-10 items-center rounded-md px-4 text-sm font-medium text-content-secondary hover:bg-hover hover:text-content">
          Cancel
        </Link>
        <Button type="submit">Next: set up units <ArrowRight className="h-4 w-4" /></Button>
      </div>
    </form>
  );
}

// ─── Step 2 ──────────────────────────────────────────────────────────────────
function UnitsStep({
  building, initial, onBack, onNext,
}: {
  building: BuildingValues;
  initial: UnitRow[] | null;
  onBack: (units: UnitRow[]) => void;
  onNext: (units: UnitRow[]) => void;
}) {
  const floors = building.total_floors;
  const defaultUnit = (i: number, floor?: number): UnitRow => ({
    label: `Unit ${i + 1}`,
    floor: floor ?? Math.min(i, floors - 1),
    unit_type: building.building_type === "BUSINESS" ? "shop" : "single",
    classification: building.building_type,
    monthly_rent: 0,
    notes: "",
  });

  // Units already set up are kept when the owner goes back to step one: a
  // higher unit count only adds rows, a lower one leaves the owner to remove
  // the extras here rather than guessing which, and a unit on a floor that no
  // longer exists moves to the top floor.
  const startingUnits = (initial ?? []).map((u) => ({ ...u, floor: Math.min(Number(u.floor), floors - 1) }));
  while (startingUnits.length < building.unit_count) startingUnits.push(defaultUnit(startingUnits.length));

  const { register, handleSubmit, control, watch, getValues, formState: { errors } } = useForm<UnitsValues>({
    resolver: zodResolver(unitsSchema),
    defaultValues: { units: startingUnits },
  });
  const { fields, append, remove } = useFieldArray({ control, name: "units" });
  const units = watch("units");

  return (
    <form onSubmit={handleSubmit((v) => onNext(v.units))} className="space-y-6">
      <p className="text-sm text-content-secondary">
        Give each unit its label, floor, type and monthly rent. Labels must be unique across every property, so use
        the building&rsquo;s code as a prefix (e.g. <span className="font-medium text-content">DON1A</span>).
      </p>

      {Array.from({ length: floors }).map((_, floor) => {
        const rows = fields.map((f, index) => ({ id: f.id, index })).filter(({ index }) => Number(units[index]?.floor) === floor);
        return (
          <section key={floor} aria-labelledby={`floor-${floor}`} className="space-y-2">
            <h3 id={`floor-${floor}`} className="text-[11px] font-semibold uppercase tracking-[0.14em] text-content-muted">
              {floorName(floor)} <span className="font-normal normal-case tracking-normal">· {rows.length} unit{rows.length === 1 ? "" : "s"}</span>
            </h3>
            <ul className="divide-y divide-hairline rounded-md border border-hairline">
              {rows.map(({ id, index }) => (
                <li key={id} className="grid gap-3 p-3 sm:grid-cols-[1fr_1fr_1fr_1fr_auto] sm:items-start">
                  <Field label="Label *" error={errors.units?.[index]?.label?.message}>
                    <input {...register(`units.${index}.label`)} className={inputCls} placeholder="e.g. DON1A" />
                  </Field>
                  <Field label="Floor">
                    <select {...register(`units.${index}.floor`)} className={inputCls}>
                      {Array.from({ length: floors }, (_, f) => <option key={f} value={f}>{floorName(f)}</option>)}
                    </select>
                  </Field>
                  <Field label="Type">
                    <select {...register(`units.${index}.unit_type`)} className={inputCls}>
                      {UNIT_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                    </select>
                  </Field>
                  <Field label="Rent (KES) *" error={errors.units?.[index]?.monthly_rent?.message}>
                    <input type="number" min={0} step={100} {...register(`units.${index}.monthly_rent`)} className={inputCls} />
                  </Field>
                  <div className="flex gap-1 sm:pt-6">
                    <button
                      type="button"
                      onClick={() => {
                        const u = getValues(`units.${index}`);
                        append({ ...u, label: `${u.label} copy` });
                      }}
                      aria-label={`Duplicate ${units[index]?.label || "unit"}`}
                      title="Duplicate"
                      className="inline-flex h-9 w-9 items-center justify-center rounded-md text-content-muted hover:bg-hover hover:text-content"
                    >
                      <Copy className="h-4 w-4" />
                    </button>
                    <button
                      type="button"
                      onClick={() => remove(index)}
                      disabled={fields.length === 1}
                      aria-label={`Remove ${units[index]?.label || "unit"}`}
                      title="Remove"
                      className="inline-flex h-9 w-9 items-center justify-center rounded-md text-danger hover:bg-danger-soft disabled:opacity-40"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </li>
              ))}
              <li>
                <button
                  type="button"
                  onClick={() => append(defaultUnit(fields.length, floor))}
                  className="flex w-full items-center justify-center gap-1.5 py-2.5 text-xs font-medium text-content-secondary hover:bg-hover hover:text-content"
                >
                  <Plus className="h-3.5 w-3.5" /> Add a unit to {floorName(floor).toLowerCase()}
                </button>
              </li>
            </ul>
          </section>
        );
      })}

      <div className="flex justify-between gap-2 border-t border-hairline pt-4">
        <Button type="button" variant="ghost" onClick={() => onBack(getValues("units"))}>
          <ArrowLeft className="h-4 w-4" /> Back
        </Button>
        <Button type="submit">Review <ArrowRight className="h-4 w-4" /></Button>
      </div>
    </form>
  );
}

// ─── Step 3 ──────────────────────────────────────────────────────────────────
function ReviewStep({
  building, units, photo, onBack, onConfirm, saving,
}: {
  building: BuildingValues; units: UnitRow[]; photo: Photo; onBack: () => void; onConfirm: () => void; saving: boolean;
}) {
  const totalRent = units.reduce((sum, u) => sum + Number(u.monthly_rent), 0);
  return (
    <div className="space-y-5">
      <div className="grid gap-6 md:grid-cols-[12rem_minmax(0,1fr)] md:items-start">
      <figure className="space-y-1">
        <img
          src={photo?.url ?? NEW_BUILDING_PLACEHOLDER}
          alt=""
          className="aspect-[4/3] w-full rounded-md border border-border object-cover"
        />
        <figcaption className="text-[11px] text-content-muted">
          {photo ? "Your photo" : "No photo: a stock picture is shown"}
        </figcaption>
      </figure>
      <dl className="grid gap-4 sm:grid-cols-4">
        <div className="sm:col-span-2">
          <dt className="text-[11px] uppercase tracking-[0.14em] text-content-muted">Building</dt>
          <dd className="font-medium text-content">{building.name}</dd>
          {building.address && <dd className="text-sm text-content-muted">{building.address}</dd>}
        </div>
        <div>
          <dt className="text-[11px] uppercase tracking-[0.14em] text-content-muted">Type</dt>
          <dd className="text-content">{building.building_type === "BUSINESS" ? "Commercial, 16% VAT" : "Residential"}</dd>
        </div>
        <div>
          <dt className="text-[11px] uppercase tracking-[0.14em] text-content-muted">Rent when fully let</dt>
          <dd className="font-display text-lg font-semibold tabular-nums text-content">{formatKES(totalRent)}</dd>
          <dd className="text-xs text-content-muted">
            {units.length} unit{units.length === 1 ? "" : "s"} on {building.total_floors} floor{building.total_floors === 1 ? "" : "s"}
          </dd>
        </div>
      </dl>
      </div>

      <Table minWidth={480}>
        <THead>
          <TR><TH>Unit</TH><TH>Floor</TH><TH>Type</TH><TH className="text-right">Rent</TH></TR>
        </THead>
        <TBody>
          {units.map((u, i) => (
            <TR key={i}>
              <TD className="font-medium text-content">{u.label}</TD>
              <TD className="text-content-muted">{floorName(Number(u.floor))}</TD>
              <TD className="text-content-muted">{UNIT_TYPES.find((t) => t.value === u.unit_type)?.label ?? u.unit_type}</TD>
              <TD className="text-right tabular-nums">{formatKES(u.monthly_rent)}</TD>
            </TR>
          ))}
        </TBody>
      </Table>

      <div className="flex justify-between gap-2 border-t border-hairline pt-4">
        <Button type="button" variant="ghost" onClick={onBack} disabled={saving}>
          <ArrowLeft className="h-4 w-4" /> Back
        </Button>
        <Button type="button" onClick={onConfirm} loading={saving}>
          <Check className="h-4 w-4" /> Create building
        </Button>
      </div>
    </div>
  );
}

// ─── Page ────────────────────────────────────────────────────────────────────
export default function AddBuildingPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const createBuilding = useCreateBuilding();
  const [step, setStep] = useState<0 | 1 | 2>(0);
  const [building, setBuilding] = useState<BuildingValues | null>(null);
  const [units, setUnits] = useState<UnitRow[] | null>(null);
  const [photo, setPhotoState] = useState<Photo>(null);
  const setPhoto = useSetBuildingPhoto();
  // One object URL per chosen photo, released when it is replaced or the page closes.
  useEffect(() => () => { if (photo) URL.revokeObjectURL(photo.url); }, [photo]);
  const choosePhoto = (blob: Blob | null) => setPhotoState(blob ? { blob, url: URL.createObjectURL(blob) } : null);
  // Set once the building row exists, so a retry after a unit failure adds the
  // units to it instead of creating the building a second time.
  const [createdId, setCreatedId] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);

  async function confirm() {
    if (!building || !units) return;
    setSaving(true);
    try {
      const details = {
        name: building.name,
        address: building.address || "",
        total_floors: building.total_floors,
        notes: building.notes || "",
      };
      let id = createdId;
      if (id == null) {
        id = (await createBuilding.mutateAsync(details)).id;
        setCreatedId(id);
      } else {
        // A retry after the units failed: the details may have been edited since.
        await api.patch(`/buildings/${id}/`, details);
      }
      await api.post(`/buildings/${id}/bulk-create-units/`, {
        units: units.map((u) => ({
          label: u.label,
          floor: Number(u.floor),
          unit_type: u.unit_type as UnitType,
          classification: u.classification as UnitClassification,
          monthly_rent: String(u.monthly_rent),
          notes: u.notes || "",
        })),
      });
      qc.invalidateQueries({ queryKey: ["buildings"] });
      qc.invalidateQueries({ queryKey: ["units"] });
      toast.success(`${building.name} created with ${units.length} unit${units.length === 1 ? "" : "s"}`);
      if (photo) {
        // The building stands without its photo, so a failed upload is only a
        // warning: it can be added later from Edit.
        try {
          await setPhoto.mutateAsync({ id, photo: photo.blob });
        } catch (e) {
          toast.error(getErrorMessage(e, "The photo could not be uploaded. Add it from Edit on the building's card."));
        }
      }
      navigate(BACK_TO);
    } catch (e) {
      toast.error(
        getErrorMessage(
          e,
          createdId == null
            ? "The building could not be created. Its name must be unique."
            : "The units could not be saved. Check the labels are unique, then try again.",
        ),
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <Link to={BACK_TO} className="mb-2 inline-flex items-center gap-1 text-sm text-content-muted hover:text-content">
          <ArrowLeft className="h-4 w-4" /> Back to Buildings
        </Link>
        {/* The step line below says where the owner is; the title is for screen readers only. */}
        <p className="text-xs font-semibold uppercase tracking-wider text-teal-700 dark:text-teal-600">New building</p>
        <h1 className="sr-only">Add a building</h1>
      </div>

      <ol className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm" aria-label="Progress">
        {STEPS.map((label, i) => (
          <li key={label} aria-current={i === step ? "step" : undefined} className="flex items-center gap-2">
            <span
              className={cn(
                "flex h-6 w-6 items-center justify-center rounded-full text-xs font-semibold tabular-nums",
                i < step ? "bg-success text-white" : i === step ? "bg-navy-800 text-white" : "bg-surface-sunk text-content-muted",
              )}
            >
              {i < step ? <Check className="h-3.5 w-3.5" /> : i + 1}
            </span>
            <span className={i === step ? "font-medium text-content" : "text-content-muted"}>{label}</span>
          </li>
        ))}
      </ol>

      <Card variant="glass" padding="md" className="animate-fade-up">
        {step === 0 && (
          <BuildingStep
            initial={building}
            photo={photo}
            onPhoto={choosePhoto}
            onNext={(v) => { setBuilding(v); setStep(1); }}
          />
        )}
        {step === 1 && building && (
          <UnitsStep
            building={building}
            initial={units}
            onBack={(u) => { setUnits(u); setStep(0); }}
            onNext={(u) => { setUnits(u); setStep(2); }}
          />
        )}
        {step === 2 && building && units && (
          <ReviewStep
            building={building}
            units={units}
            photo={photo}
            onBack={() => setStep(1)}
            onConfirm={confirm}
            saving={saving}
          />
        )}
      </Card>
    </div>
  );
}
