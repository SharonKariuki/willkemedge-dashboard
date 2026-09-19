/**
 * The owner's credit and refund dialogs.
 *
 * The words here are a property manager's, not an accountant's: "Add Credit",
 * "Credit on Account", "Apply to Next Invoice", "Refund Credit". The accounting
 * behind each choice — which account a credit is charged to, the VAT that
 * comes back on a credit note — is decided on the server from the reason
 * chosen, and the dialogs only ever describe its effect on the tenant.
 */
import { AlertTriangle, Ban, Send, Undo2 } from "lucide-react";
import { useMemo, useState } from "react";
import toast from "react-hot-toast";
import { Link } from "react-router-dom";

import { Button, DatePicker, Modal, Skeleton } from "@/components/ui";
import { Field, inputCls } from "@/features/tenants/shared";
import {
  type CreditReasonValue,
  type Refund,
  type TenantCredit,
  useAddCredit,
  useCloseRefund,
  useCreateRefund,
  useCreditPosition,
  useMarkRefundSent,
  useVoidCredit,
  useVoidCreditPreview,
} from "@/hooks/useCredits";
import { getErrorMessage } from "@/lib/apiError";
import { toDayFirst, todayIso } from "@/lib/dates";
import { formatBalanceKES, formatKES } from "@/lib/money";

const KES = formatKES;
const round2 = (n: number) => Math.round(n * 100) / 100;

const METHODS: { value: Refund["method"]; label: string }[] = [
  { value: "mpesa", label: "M-Pesa" },
  { value: "bank", label: "Bank transfer" },
  { value: "cash", label: "Cash" },
  { value: "cheque", label: "Cheque" },
];

/** Methods that leave a trace on a statement, so the reference is required. */
const NEEDS_REFERENCE = new Set<Refund["method"]>(["mpesa", "bank", "cheque"]);

function Note({ tone = "muted", children }: { tone?: "muted" | "warn"; children: React.ReactNode }) {
  return tone === "warn" ? (
    <p className="mt-3 flex items-start gap-1.5 rounded-md bg-warning-soft px-3 py-2.5 text-xs text-warning">
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <span>{children}</span>
    </p>
  ) : (
    <p className="mt-2 text-[11px] leading-relaxed text-ink-500">{children}</p>
  );
}

// ─── Add Credit ─────────────────────────────────────────────────────────────

export function AddCreditModal({
  tenantId, tenantName, onClose,
}: {
  tenantId: number;
  tenantName: string;
  onClose: () => void;
}) {
  const { data: position, isLoading } = useCreditPosition(tenantId);
  const addCredit = useAddCredit();

  const [step, setStep] = useState<"form" | "review">("form");
  const [reason, setReason] = useState<CreditReasonValue | "">("");
  const [chargeKind, setChargeKind] = useState<"rent" | "water">("rent");
  const [chargeId, setChargeId] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [amount, setAmount] = useState("");
  const [creditDate, setCreditDate] = useState(todayIso());
  const [reference, setReference] = useState("");
  const [description, setDescription] = useState("");
  const [internalNotes, setInternalNotes] = useState("");
  const [evidence, setEvidence] = useState<File | null>(null);
  const [hold, setHold] = useState(false);
  const [error, setError] = useState("");

  const option = position?.reasons.find((r) => r.value === reason);
  const kind = option?.rent_only ? "rent" : chargeKind;
  const charges = kind === "rent" ? position?.rent_charges ?? [] : position?.water_charges ?? [];
  const charge = option?.needs_charge ? charges.find((c) => String(c.id) === chargeId) : undefined;

  const net = Number(amount) || 0;
  const vat = charge ? round2(net * Number(charge.vat_rate || 0)) : 0;
  const total = round2(net + vat);
  const balanceNow = Number(position?.balance ?? 0);
  const balanceAfter = round2(balanceNow - total);

  function validate(): string {
    if (!option) return "Choose why the tenant is getting this credit.";
    if (option.needs_charge && !charge) return "Choose the charge this credit corrects.";
    if (!(net > 0)) return "Enter an amount greater than zero.";
    if (charge && net > Number(charge.creditable)) {
      return `Only ${KES(charge.creditable)} of that charge can still be credited.`;
    }
    if (option.needs_category && !categoryId) return "Choose what kind of cost the tenant paid for.";
    if (!creditDate) return "Enter the date of the credit.";
    if (creditDate > todayIso()) return "A credit cannot be dated in the future.";
    if (!description.trim()) return "Explain the credit — it is printed on the tenant's statement.";
    if (option.evidence_required && !evidence) return "Attach the supporting document for this kind of credit.";
    return "";
  }

  function review() {
    const problem = validate();
    setError(problem);
    if (!problem) setStep("review");
  }

  async function issue() {
    const form = new FormData();
    form.append("tenant", String(tenantId));
    form.append("reason", reason);
    form.append("amount", net.toFixed(2));
    form.append("credit_date", creditDate);
    form.append("description", description.trim());
    form.append("internal_notes", internalNotes.trim());
    form.append("reference", reference.trim());
    form.append("hold", String(hold));
    if (charge && kind === "rent") form.append("arrears", String(charge.id));
    if (charge && kind === "water") form.append("utility_charge", String(charge.id));
    if (option?.needs_category) form.append("expense_category", categoryId);
    if (evidence) form.append("evidence", evidence);
    try {
      const credit = await addCredit.mutateAsync(form);
      const applied = Number(credit.amount_applied);
      toast.success(
        applied > 0
          ? `${credit.number} added. ${KES(applied)} cleared what was owed; ${KES(credit.remaining)} is Credit on Account.`
          : `${credit.number} added — ${KES(credit.amount)} Credit on Account.`,
      );
      onClose();
    } catch (e) {
      toast.error(getErrorMessage(e, "The credit could not be added."));
      setStep("form");
    }
  }

  const footer = step === "form" ? (
    <>
      <Button variant="ghost" onClick={onClose}>Cancel</Button>
      <Button onClick={review} disabled={isLoading}>Review credit</Button>
    </>
  ) : (
    <>
      <Button variant="ghost" onClick={() => setStep("form")}>Back</Button>
      <Button onClick={issue} loading={addCredit.isPending}>Issue Credit</Button>
    </>
  );

  return (
    <Modal open onClose={onClose} size="lg" eyebrow={tenantName} title="Add Credit" closeOnBackdrop={false} footer={footer}>
      {isLoading || !position ? (
        <Skeleton className="h-64" />
      ) : step === "form" ? (
        <div className="space-y-4">
          <Field label="Why is the tenant getting this credit? *">
            <select
              value={reason}
              onChange={(e) => { setReason(e.target.value as CreditReasonValue); setChargeId(""); }}
              className={inputCls}
            >
              <option value="">Choose a reason…</option>
              {position.reasons.map((r) => (
                <option key={r.value} value={r.value}>{r.label}</option>
              ))}
            </select>
          </Field>
          <Note>
            Tenant paid money that isn&apos;t recorded? <Link className="text-teal-700 underline" to="/payments">Record a payment</Link> instead.
            {" "}A payment recorded against the wrong tenant or amount? Void or correct the payment.
          </Note>

          {option?.needs_charge && (
            <div className="grid gap-4 sm:grid-cols-2">
              {!option.rent_only && (
                <Field label="Which charge?">
                  <select
                    value={chargeKind}
                    onChange={(e) => { setChargeKind(e.target.value as "rent" | "water"); setChargeId(""); }}
                    className={inputCls}
                  >
                    <option value="rent">Rent</option>
                    <option value="water">Water / other charge</option>
                  </select>
                </Field>
              )}
              <Field label={option.rent_only ? "Which month's rent? *" : "Charge *"}>
                <select value={chargeId} onChange={(e) => setChargeId(e.target.value)} className={inputCls}>
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
            <Field label="What kind of cost? *">
              <select value={categoryId} onChange={(e) => setCategoryId(e.target.value)} className={inputCls}>
                <option value="">Choose…</option>
                {position.expense_categories.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
            </Field>
          )}

          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              label={vat > 0 || Number(charge?.vat_rate) > 0 ? "Amount before VAT (KES) *" : "Amount (KES) *"}
              hint={charge ? `Up to ${KES(charge.creditable)}` : undefined}
            >
              <input
                inputMode="decimal"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                className={inputCls}
                placeholder="5000"
              />
            </Field>
            <DatePicker label="Date *" value={creditDate} onChange={(e) => setCreditDate(e.target.value)} />
          </div>
          {vat > 0 && (
            <p className="-mt-2 text-xs text-ink-500">
              {KES(net)} + VAT {KES(vat)} = <span className="font-medium text-ink-900">{KES(total)} credit</span>
            </p>
          )}

          <Field label="Explanation for the tenant *" hint="Printed on the tenant's statement.">
            <input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              maxLength={200}
              className={inputCls}
              placeholder="e.g. September rent billed at 15,000; agreed rent is 10,000"
            />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Reference" hint="Complaint no., meter-reading ref…">
              <input value={reference} onChange={(e) => setReference(e.target.value)} className={inputCls} />
            </Field>
            <Field label={option?.evidence_required ? "Supporting document *" : "Supporting document"} hint="PDF or photo, up to 5 MB.">
              <input
                type="file"
                accept=".pdf,.jpg,.jpeg,.png,.webp"
                onChange={(e) => setEvidence(e.target.files?.[0] ?? null)}
                className="w-full text-sm text-ink-700"
              />
            </Field>
          </div>
          <Field label="Internal note" hint="Never shown to the tenant.">
            <textarea rows={2} value={internalNotes} onChange={(e) => setInternalNotes(e.target.value)} className={inputCls} />
          </Field>

          <fieldset className="space-y-1.5">
            <legend className="mb-1 text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">
              What should happen to this credit?
            </legend>
            <label className="flex items-start gap-2 text-sm text-ink-900">
              <input type="radio" name="credit-use" checked={!hold} onChange={() => setHold(false)} className="mt-1" />
              <span><span className="font-medium">Apply to Next Invoice</span> — use it on anything owed now, then on future invoices.</span>
            </label>
            <label className="flex items-start gap-2 text-sm text-ink-900">
              <input type="radio" name="credit-use" checked={hold} onChange={() => setHold(true)} className="mt-1" />
              <span><span className="font-medium">Hold Credit</span> — keep it aside, e.g. while deciding whether to refund it.</span>
            </label>
          </fieldset>

          {error && <Note tone="warn">{error}</Note>}
        </div>
      ) : (
        <div className="space-y-3 text-sm text-ink-900">
          <p>
            <span className="font-medium">{tenantName}</span>
            <span className="text-ink-500"> · {option?.label}{charge ? ` · ${charge.label}` : ""}</span>
          </p>
          <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1.5 rounded-md bg-surface-sunk px-4 py-3 tabular-nums">
            <dt className="text-ink-500">Credit</dt>
            <dd className="text-right font-semibold">{KES(total)}{vat > 0 ? ` (incl. VAT ${KES(vat)})` : ""}</dd>
            <dt className="text-ink-500">Date</dt>
            <dd className="text-right">{toDayFirst(creditDate)}</dd>
            <dt className="text-ink-500">Balance now</dt>
            <dd className="text-right">{formatBalanceKES(balanceNow)}</dd>
            <dt className="text-ink-500">After this credit</dt>
            <dd className="text-right font-semibold">
              {balanceAfter < 0 ? `Credit on Account ${KES(-balanceAfter)}` : formatBalanceKES(balanceAfter)}
            </dd>
          </dl>
          <p className="text-ink-700">&ldquo;{description.trim()}&rdquo;</p>
          <p className="text-ink-700">
            {hold
              ? "The credit will be held: it won't be used on any invoice until you choose Apply to Next Invoice, or refund it."
              : balanceNow > 0
                ? "It will clear what the tenant owes now first; anything left applies to the next invoice."
                : "It will apply to the next invoice automatically."}
          </p>
          <Note>
            A credit can&apos;t be edited once issued — only voided, with a reason. It is numbered,
            recorded against your name and posted to the accounts.
          </Note>
        </div>
      )}
    </Modal>
  );
}

// ─── Refund Credit ──────────────────────────────────────────────────────────

export function RefundCreditModal({
  tenantId, tenantName, credit, onClose,
}: {
  tenantId: number;
  tenantName: string;
  /** Refund from this credit only; omitted = from the whole Credit on Account. */
  credit?: TenantCredit;
  onClose: () => void;
}) {
  const { data: position, isLoading } = useCreditPosition(tenantId);
  const createRefund = useCreateRefund();

  const refundable = Number(position?.refundable ?? 0);
  const limit = credit ? Math.min(Number(credit.remaining), refundable) : refundable;

  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState<Refund["method"]>("mpesa");
  const [paidTo, setPaidTo] = useState<string | null>(null);
  const [alreadySent, setAlreadySent] = useState(true);
  const [sentOn, setSentOn] = useState(todayIso());
  const [reference, setReference] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState("");

  const shownAmount = amount === "" && limit > 0 ? String(limit) : amount;
  const shownPaidTo = paidTo ?? (method === "mpesa" ? position?.tenant_phone ?? "" : "");
  const payeeDiffers =
    method === "mpesa" && !!position?.tenant_phone && shownPaidTo.trim() !== position.tenant_phone.trim();

  async function submit() {
    const value = Number(shownAmount) || 0;
    let problem = "";
    if (!(value > 0)) problem = "Enter the amount to refund.";
    else if (value > limit) problem = `Only ${KES(limit)} can be refunded right now.`;
    else if (alreadySent && !sentOn) problem = "Enter the date the money was sent.";
    else if (alreadySent && NEEDS_REFERENCE.has(method) && !reference.trim()) {
      problem = "Enter the transaction reference of the money you sent.";
    }
    setError(problem);
    if (problem) return;
    try {
      const refund = await createRefund.mutateAsync({
        tenant: tenantId,
        amount: value.toFixed(2),
        method,
        paid_to: shownPaidTo.trim(),
        reference: reference.trim(),
        notes: notes.trim(),
        already_sent: alreadySent,
        sent_on: alreadySent ? sentOn : null,
        credit: credit?.id ?? null,
      });
      toast.success(
        refund.status === "sent"
          ? `${refund.number}: ${KES(refund.amount)} refunded.`
          : `${refund.number}: ${KES(refund.amount)} set aside as a refund to send.`,
      );
      onClose();
    } catch (e) {
      toast.error(getErrorMessage(e, "The refund could not be recorded."));
    }
  }

  return (
    <Modal
      open onClose={onClose} size="md" eyebrow={tenantName}
      title={credit ? `Refund Credit — ${credit.number}` : "Refund Credit"}
      closeOnBackdrop={false}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button onClick={submit} loading={createRefund.isPending} disabled={isLoading || limit <= 0}>
            <Send className="h-4 w-4" /> {alreadySent ? "Record Refund" : "Schedule Refund"}
          </Button>
        </>
      }
    >
      {isLoading || !position ? (
        <Skeleton className="h-48" />
      ) : limit <= 0 ? (
        <Note tone="warn">
          Nothing can be refunded. Once everything the tenant owes is counted — including rent
          already invoiced for next month — they are not in credit.
        </Note>
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-ink-700">
            Up to <span className="font-semibold text-ink-900">{KES(limit)}</span> can be refunded.
          </p>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Amount (KES) *">
              <input inputMode="decimal" value={shownAmount} onChange={(e) => setAmount(e.target.value)} className={inputCls} />
            </Field>
            <Field label="Method *">
              <select value={method} onChange={(e) => setMethod(e.target.value as Refund["method"])} className={inputCls}>
                {METHODS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
              </select>
            </Field>
          </div>
          <Field label="Paid to" hint={method === "bank" ? "Bank and account number." : "Phone number."}>
            <input value={shownPaidTo} onChange={(e) => setPaidTo(e.target.value)} className={inputCls} />
          </Field>
          {payeeDiffers && <Note tone="warn">This isn&apos;t the tenant&apos;s registered number.</Note>}

          <fieldset className="space-y-1.5">
            <legend className="mb-1 text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">
              Has the money already been sent?
            </legend>
            <label className="flex items-center gap-2 text-sm">
              <input type="radio" name="sent" checked={alreadySent} onChange={() => setAlreadySent(true)} />
              Yes — record it now
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="radio" name="sent" checked={!alreadySent} onChange={() => setAlreadySent(false)} />
              No, I&apos;ll send it later (the amount is set aside)
            </label>
          </fieldset>

          {alreadySent && (
            <div className="grid gap-4 sm:grid-cols-2">
              <DatePicker label="Date sent *" value={sentOn} onChange={(e) => setSentOn(e.target.value)} />
              <Field label={NEEDS_REFERENCE.has(method) ? "Transaction reference *" : "Reference"}>
                <input value={reference} onChange={(e) => setReference(e.target.value)} className={inputCls} placeholder="e.g. QX7…" />
              </Field>
            </div>
          )}
          <Field label="Note">
            <input value={notes} onChange={(e) => setNotes(e.target.value)} className={inputCls} maxLength={255} />
          </Field>
          {error && <Note tone="warn">{error}</Note>}
        </div>
      )}
    </Modal>
  );
}

// ─── Mark as Sent ───────────────────────────────────────────────────────────

export function MarkRefundSentModal({ refund, onClose }: { refund: Refund; onClose: () => void }) {
  const markSent = useMarkRefundSent();
  const [sentOn, setSentOn] = useState(todayIso());
  const [method, setMethod] = useState<Refund["method"]>(refund.method);
  const [reference, setReference] = useState(refund.reference);

  async function submit() {
    if (NEEDS_REFERENCE.has(method) && !reference.trim()) {
      toast.error("Enter the transaction reference of the money you sent.");
      return;
    }
    try {
      await markSent.mutateAsync({ id: refund.id, sent_on: sentOn, reference: reference.trim(), method });
      toast.success(`${refund.number} marked as sent.`);
      onClose();
    } catch (e) {
      toast.error(getErrorMessage(e, "Could not mark the refund as sent."));
    }
  }

  return (
    <Modal
      open onClose={onClose} size="sm" eyebrow={refund.number} title="Mark as Sent" closeOnBackdrop={false}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button onClick={submit} loading={markSent.isPending}>Mark as Sent</Button>
        </>
      }
    >
      <p className="text-sm text-ink-700">{KES(refund.amount)} to {refund.paid_to || "the tenant"}.</p>
      <div className="mt-4 space-y-4">
        <DatePicker label="Date sent *" value={sentOn} onChange={(e) => setSentOn(e.target.value)} />
        <Field label="Method">
          <select value={method} onChange={(e) => setMethod(e.target.value as Refund["method"])} className={inputCls}>
            {METHODS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
          </select>
        </Field>
        <Field label={NEEDS_REFERENCE.has(method) ? "Transaction reference *" : "Reference"}>
          <input value={reference} onChange={(e) => setReference(e.target.value)} className={inputCls} />
        </Field>
      </div>
    </Modal>
  );
}

// ─── Void Credit ────────────────────────────────────────────────────────────

export function VoidCreditModal({
  credit, tenantName, onClose,
}: {
  credit: TenantCredit;
  tenantName: string;
  onClose: () => void;
}) {
  const { data: preview, isLoading, isError } = useVoidCreditPreview(credit.id);
  const voidCredit = useVoidCredit();
  const [reason, setReason] = useState("");

  const consequences = useMemo(() => {
    if (!preview) return [];
    const lines: string[] = [];
    for (const r of preview.reopened) lines.push(`${KES(r.amount)} goes back onto ${r.label} (it was paid with this credit).`);
    if (Number(preview.refunds_cancelled) > 0) {
      lines.push(`The refund still to be sent (${KES(preview.refunds_cancelled)}) is cancelled.`);
    }
    if (Number(preview.refunded_kept) > 0) {
      lines.push(`${KES(preview.refunded_kept)} was already refunded. That money has left, so ${tenantName} will owe it.`);
    }
    return lines;
  }, [preview, tenantName]);

  async function submit() {
    try {
      await voidCredit.mutateAsync({ id: credit.id, reason: reason.trim() });
      toast.success(`${credit.number} voided.`);
      onClose();
    } catch (e) {
      toast.error(getErrorMessage(e, "The credit could not be voided."));
    }
  }

  return (
    <Modal
      open onClose={onClose} size="sm" eyebrow="Correction" title={`Void Credit ${credit.number}`}
      closeOnBackdrop={false}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="danger" onClick={submit} loading={voidCredit.isPending} disabled={isLoading || isError || !reason.trim()}>
            <Undo2 className="h-4 w-4" /> Void Credit
          </Button>
        </>
      }
    >
      <p className="text-sm text-ink-900">
        {KES(credit.amount)} · {credit.reason_display}
      </p>
      {isLoading ? (
        <Skeleton className="mt-4 h-16" />
      ) : isError ? (
        <Note tone="warn">Could not check what this credit has been used for. Close and retry.</Note>
      ) : consequences.length ? (
        <div className="mt-3 rounded-md bg-warning-soft px-3 py-3 text-xs text-warning">
          <p className="font-medium">This credit has been used. Voiding it will:</p>
          <ul className="mt-1.5 list-disc space-y-1 pl-4">
            {consequences.map((c) => <li key={c}>{c}</li>)}
          </ul>
          {Number(preview?.tenant_will_owe_more_by) > 0 && (
            <p className="mt-2 font-medium">
              {tenantName}&apos;s balance goes up by {KES(preview?.tenant_will_owe_more_by)}.
            </p>
          )}
        </div>
      ) : (
        <Note>This credit hasn&apos;t been used, so voiding it simply removes it from the account.</Note>
      )}
      <label htmlFor="void-credit-reason" className="mb-1 mt-4 block text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">
        Reason *
      </label>
      <textarea id="void-credit-reason" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} className={inputCls} />
      <Note>
        Nothing is deleted. The credit stays in Credit History marked void, against your name, and
        the accounts get a reversing entry dated today.
      </Note>
    </Modal>
  );
}

// ─── Cancel / Void Refund ───────────────────────────────────────────────────

export function CloseRefundModal({
  refund, action, onClose,
}: {
  refund: Refund;
  action: "cancel" | "void";
  onClose: () => void;
}) {
  const closeRefund = useCloseRefund();
  const [reason, setReason] = useState("");
  const isVoid = action === "void";

  async function submit() {
    try {
      await closeRefund.mutateAsync({ id: refund.id, action, reason: reason.trim() });
      toast.success(`${refund.number} ${isVoid ? "voided" : "cancelled"}. The credit is available again.`);
      onClose();
    } catch (e) {
      toast.error(getErrorMessage(e, "Could not update the refund."));
    }
  }

  return (
    <Modal
      open onClose={onClose} size="sm" eyebrow={refund.number}
      title={isVoid ? "Void Refund" : "Cancel Refund"} closeOnBackdrop={false}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Back</Button>
          <Button variant="danger" onClick={submit} loading={closeRefund.isPending} disabled={!reason.trim()}>
            <Ban className="h-4 w-4" /> {isVoid ? "Void Refund" : "Cancel Refund"}
          </Button>
        </>
      }
    >
      <p className="text-sm text-ink-900">{KES(refund.amount)} by {refund.method_display}{refund.reference ? `, ref ${refund.reference}` : ""}</p>
      <Note>
        {isVoid
          ? "Only void a refund if the money did not reach the tenant or came back. The credit becomes available again and the accounts get a reversing entry dated today."
          : "The refund was never sent, so nothing reached the accounts. The amount goes back to Credit on Account."}
      </Note>
      <label htmlFor="close-refund-reason" className="mb-1 mt-4 block text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">
        Reason *
      </label>
      <textarea id="close-refund-reason" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} className={inputCls} />
    </Modal>
  );
}
