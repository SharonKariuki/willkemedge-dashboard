/**
 * AddCreditPage — /tenants/:id/credits/new
 *
 * Adding a credit is a form with a reason, a charge to correct, money, an
 * explanation the tenant will read and a document to attach, so it gets a page
 * rather than a dialog: the fields have room, the summary beside them keeps the
 * effect on the tenant's balance in view, and the work survives a stray click.
 *
 * Two steps on purpose. A credit cannot be edited once issued — only voided —
 * so the second step states what it will do before the owner commits to it.
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
import { type CreditReasonValue, useAddCredit, useCreditPosition } from "@/hooks/useCredits";
import { useTenant } from "@/hooks/useTenants";
import { getErrorMessage } from "@/lib/apiError";
import { toDayFirst, todayIso } from "@/lib/dates";
import { formatBalanceKES } from "@/lib/money";

const schema = z.object({
  reason: z.string().min(1, "Choose why the tenant is getting this credit."),
  chargeKind: z.enum(["rent", "water"]),
  chargeId: z.string(),
  categoryId: z.string(),
  amount: z.string().refine((v) => Number(v) > 0, "Enter an amount greater than zero."),
  creditDate: z.string().min(1, "Enter the date of the credit.")
    .refine((v) => v <= todayIso(), "A credit cannot be dated in the future."),
  reference: z.string().optional(),
  description: z.string().trim().min(1, "Explain the credit — it is printed on the tenant's statement."),
  internalNotes: z.string().optional(),
  hold: z.boolean(),
});
type FormValues = z.infer<typeof schema>;

export default function AddCreditPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const { data: tenant, isLoading: tenantLoading } = useTenant(id ?? null);
  const { data: position, isLoading } = useCreditPosition(id ?? null);
  const addCredit = useAddCredit();

  const [step, setStep] = useState<"form" | "review">("form");
  const [evidence, setEvidence] = useState<File | null>(null);
  const [evidenceError, setEvidenceError] = useState("");

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      reason: "", chargeKind: "rent", chargeId: "", categoryId: "", amount: "",
      creditDate: todayIso(), reference: "", description: "", internalNotes: "", hold: false,
    },
  });
  const values = form.watch();

  const option = position?.reasons.find((r) => r.value === values.reason);
  const kind = option?.rent_only ? "rent" : values.chargeKind;
  const charges = kind === "rent" ? position?.rent_charges ?? [] : position?.water_charges ?? [];
  const charge = option?.needs_charge ? charges.find((c) => String(c.id) === values.chargeId) : undefined;

  const net = Number(values.amount) || 0;
  const vat = charge ? round2(net * Number(charge.vat_rate || 0)) : 0;
  const total = round2(net + vat);
  const balanceNow = Number(position?.balance ?? 0);
  const balanceAfter = round2(balanceNow - total);
  const backTo = `/tenants/${id}`;

  function review(data: FormValues) {
    setEvidenceError("");
    if (option?.needs_charge && !charge) {
      form.setError("chargeId", { message: "Choose the charge this credit corrects." });
      return;
    }
    if (charge && net > Number(charge.creditable)) {
      form.setError("amount", {
        message: `Only ${KES(charge.creditable)} of that charge can still be credited.`,
      });
      return;
    }
    if (option?.needs_category && !data.categoryId) {
      form.setError("categoryId", { message: "Choose what kind of cost the tenant paid for." });
      return;
    }
    if (option?.evidence_required && !evidence) {
      setEvidenceError("Attach the supporting document for this kind of credit.");
      return;
    }
    setStep("review");
  }

  async function issue() {
    const data = form.getValues();
    const body = new FormData();
    body.append("tenant", String(tenant?.id ?? id));
    body.append("reason", data.reason);
    body.append("amount", net.toFixed(2));
    body.append("credit_date", data.creditDate);
    body.append("description", data.description.trim());
    body.append("internal_notes", (data.internalNotes ?? "").trim());
    body.append("reference", (data.reference ?? "").trim());
    body.append("hold", String(data.hold));
    if (charge && kind === "rent") body.append("arrears", String(charge.id));
    if (charge && kind === "water") body.append("utility_charge", String(charge.id));
    if (option?.needs_category) body.append("expense_category", data.categoryId);
    if (evidence) body.append("evidence", evidence);
    try {
      const credit = await addCredit.mutateAsync(body);
      const applied = Number(credit.amount_applied);
      toast.success(
        applied > 0
          ? `${credit.number} added. ${KES(applied)} cleared what was owed; ${KES(credit.remaining)} is Credit on Account.`
          : `${credit.number} added — ${KES(credit.amount)} Credit on Account.`,
      );
      navigate(`${backTo}#credit-history`);
    } catch (e) {
      toast.error(getErrorMessage(e, "The credit could not be added."));
      setStep("form");
    }
  }

  if (!user?.can_forgive_money) {
    return (
      <ErrorState
        title="Only the owner can add a credit."
        description="Credits and refunds carry the same privilege as waiving arrears or voiding a payment."
      />
    );
  }
  if (isLoading || tenantLoading || !position || !tenant) {
    return <div className="space-y-4">{Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-40" />)}</div>;
  }

  return (
    <div>
      <Link to={backTo} className="mb-2 inline-flex items-center gap-1 text-sm text-content-muted hover:text-content">
        <ArrowLeft className="h-4 w-4" /> Back to {tenant.full_name}
      </Link>
      <PageHeader
        eyebrow={`${tenant.building_name} · Unit ${tenant.unit_label}`}
        title="Add Credit"
        description={
          step === "form"
            ? "A credit is a numbered record on the tenant's account. It can be used against their next invoice, or refunded."
            : "Check the figures. A credit cannot be edited once issued — only voided, with a reason."
        }
      />

      <div className="grid gap-6 lg:grid-cols-3">
        <Card padding="md" className="lg:col-span-2">
          {step === "form" ? (
            <form onSubmit={form.handleSubmit(review)} className="space-y-4">
              <Field label="Why is the tenant getting this credit? *" error={form.formState.errors.reason?.message}>
                <select
                  {...form.register("reason")}
                  onChange={(e) => {
                    form.setValue("reason", e.target.value as CreditReasonValue);
                    form.setValue("chargeId", "");
                  }}
                  className={inputCls}
                >
                  <option value="">Choose a reason…</option>
                  {position.reasons.map((r) => (
                    <option key={r.value} value={r.value}>{r.label}</option>
                  ))}
                </select>
              </Field>
              <Note>
                Tenant paid money that isn&apos;t recorded?{" "}
                <Link className="text-teal-700 underline" to="/payments">Record a payment</Link> instead.
                {" "}A payment recorded against the wrong tenant or amount? Void or correct the payment.
              </Note>

              {option?.needs_charge && (
                <div className="grid gap-4 sm:grid-cols-2">
                  {!option.rent_only && (
                    <Field label="Which charge?">
                      <select
                        {...form.register("chargeKind")}
                        onChange={(e) => {
                          form.setValue("chargeKind", e.target.value as "rent" | "water");
                          form.setValue("chargeId", "");
                        }}
                        className={inputCls}
                      >
                        <option value="rent">Rent</option>
                        <option value="water">Water / other charge</option>
                      </select>
                    </Field>
                  )}
                  <Field
                    label={option.rent_only ? "Which month's rent? *" : "Charge *"}
                    error={form.formState.errors.chargeId?.message}
                  >
                    <select {...form.register("chargeId")} className={inputCls}>
                      <option value="">Choose…</option>
                      {charges.map((c) => (
                        <option key={c.id} value={c.id} disabled={Number(c.creditable) <= 0}>
                          {c.label} — {KES(c.charged)}{Number(c.creditable) <= 0 ? " (fully credited)" : ""}
                        </option>
                      ))}
                    </select>
                  </Field>
                </div>
              )}

              {option?.needs_category && (
                <Field label="What kind of cost? *" error={form.formState.errors.categoryId?.message}>
                  <select {...form.register("categoryId")} className={inputCls}>
                    <option value="">Choose…</option>
                    {position.expense_categories.map((c) => (
                      <option key={c.id} value={c.id}>{c.name}</option>
                    ))}
                  </select>
                </Field>
              )}

              <div className="grid gap-4 sm:grid-cols-2">
                <Field
                  label={Number(charge?.vat_rate) > 0 ? "Amount before VAT (KES) *" : "Amount (KES) *"}
                  hint={charge ? `Up to ${KES(charge.creditable)}` : undefined}
                  error={form.formState.errors.amount?.message}
                >
                  <input inputMode="decimal" {...form.register("amount")} className={inputCls} placeholder="5000" />
                </Field>
                <Controller
                  control={form.control}
                  name="creditDate"
                  render={({ field }) => (
                    <DatePicker
                      label="Date *"
                      value={field.value}
                      onChange={field.onChange}
                      error={form.formState.errors.creditDate?.message}
                    />
                  )}
                />
              </div>

              <Field
                label="Explanation for the tenant *"
                hint="Printed on the tenant's statement."
                error={form.formState.errors.description?.message}
              >
                <input
                  {...form.register("description")}
                  maxLength={200}
                  className={inputCls}
                  placeholder="e.g. September rent billed at 15,000; agreed rent is 10,000"
                />
              </Field>

              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Reference" hint="Complaint no., meter-reading ref…">
                  <input {...form.register("reference")} className={inputCls} />
                </Field>
                <Field
                  label={option?.evidence_required ? "Supporting document *" : "Supporting document"}
                  hint="PDF or photo, up to 5 MB."
                  error={evidenceError}
                >
                  <input
                    type="file"
                    accept=".pdf,.jpg,.jpeg,.png,.webp"
                    onChange={(e) => { setEvidence(e.target.files?.[0] ?? null); setEvidenceError(""); }}
                    className="w-full text-sm text-ink-700"
                  />
                </Field>
              </div>

              <Field label="Internal note" hint="Never shown to the tenant.">
                <textarea rows={2} {...form.register("internalNotes")} className={inputCls} />
              </Field>

              <fieldset className="space-y-1.5">
                <legend className="mb-1 text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">
                  What should happen to this credit?
                </legend>
                <label className="flex items-start gap-2 text-sm text-ink-900">
                  <input type="radio" checked={!values.hold} onChange={() => form.setValue("hold", false)} className="mt-1" />
                  <span><span className="font-medium">Apply to Next Invoice</span> — use it on anything owed now, then on future invoices.</span>
                </label>
                <label className="flex items-start gap-2 text-sm text-ink-900">
                  <input type="radio" checked={values.hold} onChange={() => form.setValue("hold", true)} className="mt-1" />
                  <span><span className="font-medium">Hold Credit</span> — keep it aside, e.g. while deciding whether to refund it.</span>
                </label>
              </fieldset>

              <div className="flex justify-end gap-2 border-t border-hairline pt-4">
                <Button type="button" variant="ghost" onClick={() => navigate(backTo)}>Cancel</Button>
                <Button type="submit">Review credit</Button>
              </div>
            </form>
          ) : (
            <div className="space-y-3 text-sm text-ink-900">
              <p>
                <span className="font-medium">{tenant.full_name}</span>
                <span className="text-ink-500"> · {option?.label}{charge ? ` · ${charge.label}` : ""}</span>
              </p>
              <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1.5 rounded-md bg-surface-sunk px-4 py-3 tabular-nums">
                <dt className="text-ink-500">Credit</dt>
                <dd className="text-right font-semibold">{KES(total)}{vat > 0 ? ` (incl. VAT ${KES(vat)})` : ""}</dd>
                <dt className="text-ink-500">Date</dt>
                <dd className="text-right">{toDayFirst(values.creditDate)}</dd>
                <dt className="text-ink-500">Balance now</dt>
                <dd className="text-right">{formatBalanceKES(balanceNow)}</dd>
                <dt className="text-ink-500">After this credit</dt>
                <dd className="text-right font-semibold">
                  {balanceAfter < 0 ? `Credit on Account ${KES(-balanceAfter)}` : formatBalanceKES(balanceAfter)}
                </dd>
              </dl>
              <p className="text-ink-700">&ldquo;{values.description.trim()}&rdquo;</p>
              <p className="text-ink-700">
                {values.hold
                  ? "The credit will be held: it won't be used on any invoice until you choose Apply to Next Invoice, or refund it."
                  : balanceNow > 0
                    ? "It will clear what the tenant owes now first; anything left applies to the next invoice."
                    : "It will apply to the next invoice automatically."}
              </p>
              <Note>
                A credit can&apos;t be edited once issued — only voided, with a reason. It is numbered,
                recorded against your name and posted to the accounts.
              </Note>
              <div className="flex justify-end gap-2 border-t border-hairline pt-4">
                <Button variant="ghost" onClick={() => setStep("form")}>Back</Button>
                <Button onClick={issue} loading={addCredit.isPending}>Issue Credit</Button>
              </div>
            </div>
          )}
        </Card>

        {/* Kept beside the form so the effect on the tenant is never out of sight. */}
        <Card padding="md" className="h-fit">
          <p className="text-xs uppercase tracking-wider text-content-muted">Summary</p>
          <dl className="mt-3 space-y-2 text-sm tabular-nums">
            <div className="flex justify-between gap-4">
              <dt className="text-ink-500">Credit</dt>
              <dd className="font-semibold text-ink-900">{KES(total)}</dd>
            </div>
            {vat > 0 && (
              <div className="flex justify-between gap-4 text-xs">
                <dt className="text-ink-500">of which VAT</dt>
                <dd className="text-ink-700">{KES(vat)}</dd>
              </div>
            )}
            <div className="flex justify-between gap-4">
              <dt className="text-ink-500">Balance now</dt>
              <dd className="text-ink-700">{formatBalanceKES(balanceNow)}</dd>
            </div>
            <div className="flex justify-between gap-4 border-t border-hairline pt-2">
              <dt className="text-ink-500">After this credit</dt>
              <dd className="font-semibold text-ink-900">
                {balanceAfter < 0 ? `${KES(-balanceAfter)} cr` : formatBalanceKES(balanceAfter)}
              </dd>
            </div>
          </dl>
          {Number(position.credit_on_account) > 0 && (
            <Note>
              {tenant.full_name.split(" ")[0]} already holds {KES(position.credit_on_account)} on account.
            </Note>
          )}
        </Card>
      </div>
    </div>
  );
}
