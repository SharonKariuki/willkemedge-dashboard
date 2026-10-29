/**
 * AddChargePage — /tenants/:id/charges/new
 *
 * A debit on the tenant's account that is not rent: a late penalty, parking, a
 * damage or repair recharge, or a flat utility bill. It shows under "Other
 * Charges" on the statement; what it is for decides the account it is booked
 * to, so the form says which account before the owner commits.
 *
 * Water from a meter is not entered here — that is the Water page,
 * which keeps the unit's meter chain continuous.
 *
 * Two steps, like Add Credit: a charge is corrected afterwards with a credit
 * note, so the second step states what it will do first.
 */
import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowLeft } from "lucide-react";
import { useState } from "react";
import { Controller, useForm } from "react-hook-form";
import toast from "react-hot-toast";
import { Link, useNavigate, useParams } from "react-router-dom";
import { z } from "zod";

import { Button, Card, DatePicker, ErrorState, PageHeader, Skeleton } from "@/components/ui";
import { Note } from "@/features/credits/Note";
import { KES, round2 } from "@/features/credits/shared";
import { Field, inputCls } from "@/features/tenants/shared";
import { useAuth } from "@/hooks/useAuth";
import { type ChargeTypeOption, useAddCharge, useChargeOptions } from "@/hooks/useCharges";
import { useCreditPosition } from "@/hooks/useCredits";
import { useTenant } from "@/hooks/useTenants";
import type { ChargeTypeValue } from "@/hooks/useWaterReadings";
import { getErrorMessage } from "@/lib/apiError";
import { toDayFirst, todayIso } from "@/lib/dates";
import { formatBalanceKES } from "@/lib/money";

/** What the statement line says unless the owner writes something better. */
const DEFAULT_LABEL: Record<ChargeTypeValue, string> = {
  electricity: "Electricity",
  garbage: "Garbage collection",
  security: "Security",
  service_charge: "Service charge",
  utility: "",
  late_fee: "Late payment penalty",
  parking: "Parking",
  damage: "",
};

const PLACEHOLDER: Record<ChargeTypeValue, string> = {
  electricity: "e.g. Electricity, October",
  garbage: "e.g. Garbage collection, October",
  security: "e.g. Security, October",
  service_charge: "e.g. Service charge, October",
  utility: "e.g. Water (not metered), October",
  late_fee: "Late payment penalty",
  parking: "Parking",
  damage: "e.g. Broken window replaced",
};

/** Charge types under the account they book to, in the order the server lists them. */
function groupByAccount(types: ChargeTypeOption[]) {
  const groups = new Map<string, ChargeTypeOption[]>();
  for (const t of types) {
    const key = t.account || "Recharge of a cost you paid — choose the expense below";
    groups.set(key, [...(groups.get(key) ?? []), t]);
  }
  return [...groups.entries()];
}

/** "2026-10" for the month a date falls in. */
function monthOf(iso: string) {
  return iso.slice(0, 7);
}

/** Next month back through the last twelve: the months a charge can belong to. */
function periodChoices(today: string) {
  const [y, m] = today.split("-").map(Number);
  return Array.from({ length: 14 }, (_, i) => {
    const d = new Date(y, m - 1 + 1 - i, 1);
    const value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
    return { value, label: d.toLocaleDateString("en-GB", { month: "long", year: "numeric" }) };
  });
}

const schema = z.object({
  chargeType: z.string().min(1, "Choose the type of charge."),
  categoryId: z.string(),
  label: z.string().trim().min(1, "Enter the reason for the charge — it is printed on the tenant's statement.")
    .max(60, "Keep the reason to 60 characters."),
  amount: z.string().refine((v) => Number(v) > 0, "Enter an amount greater than zero."),
  postingDate: z.string().min(1, "Enter the date of the charge.")
    .refine((v) => v <= todayIso(), "A charge cannot be dated in the future."),
  period: z.string().min(1, "Choose the month the charge belongs to."),
  notes: z.string().optional(),
});
type FormValues = z.infer<typeof schema>;

export default function AddChargePage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const isOwner = Boolean(user?.can_forgive_money);
  const { data: tenant, isLoading: tenantLoading } = useTenant(id ?? null);
  const { data: position, isLoading: positionLoading } = useCreditPosition(isOwner ? id ?? null : null);
  const { data: options, isLoading: optionsLoading } = useChargeOptions(isOwner);
  const addCharge = useAddCharge();

  const [step, setStep] = useState<"form" | "review">("form");
  const today = todayIso();

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      chargeType: "", categoryId: "", label: "", amount: "",
      postingDate: today, period: monthOf(today), notes: "",
    },
  });
  const values = form.watch();

  const type = options?.charge_types.find((t) => t.value === values.chargeType);
  const isDamage = values.chargeType === "damage";
  const category = options?.expense_categories.find((c) => String(c.id) === values.categoryId);
  const bookedTo = isDamage ? category?.account : type?.account;
  const period = periodChoices(today).find((p) => p.value === values.period);

  const amount = round2(Number(values.amount) || 0);
  const balanceNow = Number(position?.balance ?? 0);
  const balanceAfter = round2(balanceNow + amount);
  const backTo = `/tenants/${id}`;

  function review(data: FormValues) {
    if (data.chargeType === "damage" && !data.categoryId) {
      form.setError("categoryId", { message: "Choose which expense this recharge recovers." });
      return;
    }
    setStep("review");
  }

  async function submit() {
    const data = form.getValues();
    const [year, month] = data.period.split("-").map(Number);
    try {
      await addCharge.mutateAsync({
        tenant: Number(tenant?.id ?? id),
        charge_type: data.chargeType as ChargeTypeValue,
        amount: amount.toFixed(2),
        label: data.label.trim(),
        posting_date: data.postingDate,
        period_month: month,
        period_year: year,
        expense_category: data.chargeType === "damage" ? Number(data.categoryId) : null,
        notes: (data.notes ?? "").trim(),
      });
      toast.success(`${KES(amount)} charged to ${tenant?.full_name ?? "the tenant"}.`);
      navigate(backTo);
    } catch (e) {
      toast.error(getErrorMessage(e, "The charge could not be added."));
      setStep("form");
    }
  }

  if (!isOwner) {
    return (
      <ErrorState
        title="Only the owner can add a charge."
        description="A charge raises what a tenant owes, the same privilege as waiving arrears or adding a credit."
      />
    );
  }
  if (tenantLoading || positionLoading || optionsLoading || !tenant || !position || !options) {
    return <div className="space-y-4">{Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-40" />)}</div>;
  }

  return (
    <div className="space-y-6">
      <div>
        <Link to={backTo} className="mb-2 inline-flex items-center gap-1 text-sm text-content-muted hover:text-content">
          <ArrowLeft className="h-4 w-4" /> Back to {tenant.full_name}
        </Link>
        <PageHeader
          className="mb-0"
          eyebrow={`${tenant.building_name} · Unit ${tenant.unit_label}`}
          title="Add Charge"
        />
      </div>

      <Card variant="glass" padding="md" className="animate-fade-up">
        {step === "form" ? (
          <form onSubmit={form.handleSubmit(review)} className="space-y-4">
            <Field
              label="Type of charge *"
              hint="Decides the account it is booked to. Write the actual reason below."
              error={form.formState.errors.chargeType?.message}
            >
              <select
                {...form.register("chargeType")}
                onChange={(e) => {
                  const next = e.target.value as ChargeTypeValue;
                  form.setValue("chargeType", next);
                  form.setValue("categoryId", "");
                  // Swap in the new type's wording unless the owner has typed their own.
                  const typed = form.getValues("label").trim();
                  if (!typed || Object.values(DEFAULT_LABEL).includes(typed)) {
                    form.setValue("label", DEFAULT_LABEL[next] ?? "");
                  }
                }}
                className={inputCls}
              >
                <option value="">Choose…</option>
                {groupByAccount(options.charge_types).map(([account, types]) => (
                  <optgroup key={account} label={account}>
                    {types.map((t) => (
                      <option key={t.value} value={t.value}>{t.label}</option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </Field>

            <Field
              label="Reason for the charge *"
              hint="Printed on the tenant's statement — say what it is for, e.g. the month or the item."
              error={form.formState.errors.label?.message}
            >
              <input
                {...form.register("label")}
                maxLength={60}
                className={inputCls}
                placeholder={type ? PLACEHOLDER[type.value] : "e.g. Garbage collection, September"}
              />
            </Field>

            <Note>
              Water from a meter reading goes on the{" "}
              <Link className="text-teal-700 underline" to="/water">Water</Link> page.
              {" "}Rent is billed automatically each month — don&apos;t add it here.
            </Note>

            {isDamage && (
              <Field
                label="Which expense does this recover? *"
                hint="The cost is shown net of what the tenant pays back."
                error={form.formState.errors.categoryId?.message}
              >
                <select {...form.register("categoryId")} className={inputCls}>
                  <option value="">Choose…</option>
                  {options.expense_categories.map((c) => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
              </Field>
            )}

            <div className="grid gap-4 sm:grid-cols-3">
              <Field label="Amount (KES) *" error={form.formState.errors.amount?.message}>
                <input inputMode="decimal" {...form.register("amount")} className={inputCls} placeholder="1500" />
              </Field>
              <Controller
                control={form.control}
                name="postingDate"
                render={({ field }) => (
                  <DatePicker
                    label="Date *"
                    value={field.value}
                    onChange={field.onChange}
                    error={form.formState.errors.postingDate?.message}
                  />
                )}
              />
              <Field
                label="Statement month *"
                hint="The month's Other Charges this adds to."
                error={form.formState.errors.period?.message}
              >
                <select {...form.register("period")} className={inputCls}>
                  {periodChoices(today).map((p) => (
                    <option key={p.value} value={p.value}>{p.label}</option>
                  ))}
                </select>
              </Field>
            </div>

            <Field label="Internal note" hint="Never shown to the tenant.">
              <textarea rows={2} {...form.register("notes")} className={inputCls} />
            </Field>

            <dl className="grid gap-x-8 gap-y-2 rounded-md bg-surface-sunk px-4 py-3 text-sm tabular-nums sm:grid-cols-3">
              <div className="flex justify-between gap-4 sm:block">
                <dt className="text-ink-500">Charge</dt>
                <dd className="font-semibold text-ink-900">{KES(amount)}</dd>
              </div>
              <div className="flex justify-between gap-4 sm:block">
                <dt className="text-ink-500">Balance now</dt>
                <dd className="text-ink-700">{formatBalanceKES(balanceNow)}</dd>
              </div>
              <div className="flex justify-between gap-4 sm:block">
                <dt className="text-ink-500">After this charge</dt>
                <dd className="font-semibold text-ink-900">
                  {balanceAfter < 0 ? `${KES(-balanceAfter)} cr` : formatBalanceKES(balanceAfter)}
                </dd>
              </div>
            </dl>
            {bookedTo && <p className="text-xs text-ink-500">Booked to {bookedTo}.</p>}

            <div className="flex justify-end gap-2 border-t border-hairline pt-4">
              <Button type="button" variant="ghost" onClick={() => navigate(backTo)}>Cancel</Button>
              <Button type="submit">Review charge</Button>
            </div>
          </form>
        ) : (
          <div className="space-y-3 text-sm text-ink-900">
            <p>
              <span className="font-medium">{tenant.full_name}</span>
              <span className="text-ink-500"> · {type?.label}{isDamage && category ? ` · ${category.name}` : ""}</span>
            </p>
            <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1.5 rounded-md bg-surface-sunk px-4 py-3 tabular-nums">
              <dt className="text-ink-500">Charge</dt>
              <dd className="text-right font-semibold">{KES(amount)}</dd>
              <dt className="text-ink-500">Date</dt>
              <dd className="text-right">{toDayFirst(values.postingDate)}</dd>
              <dt className="text-ink-500">Statement month</dt>
              <dd className="text-right">{period?.label}</dd>
              <dt className="text-ink-500">Booked to</dt>
              <dd className="text-right">{bookedTo}</dd>
              <dt className="text-ink-500">Balance now</dt>
              <dd className="text-right">{formatBalanceKES(balanceNow)}</dd>
              <dt className="text-ink-500">After this charge</dt>
              <dd className="text-right font-semibold">
                {balanceAfter < 0 ? `Credit on Account ${KES(-balanceAfter)}` : formatBalanceKES(balanceAfter)}
              </dd>
            </dl>
            <p className="text-ink-700">&ldquo;{values.label.trim()}&rdquo;</p>
            <Note>
              The charge is recorded against your name and posted to the accounts. To undo it later,
              add a credit — &ldquo;We charged too much&rdquo; — against this charge.
            </Note>
            <div className="flex justify-end gap-2 border-t border-hairline pt-4">
              <Button variant="ghost" onClick={() => setStep("form")}>Back</Button>
              <Button onClick={submit} loading={addCharge.isPending}>Add Charge</Button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
