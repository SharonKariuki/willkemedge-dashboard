/**
 * RefundCreditPage — /tenants/:id/credits/refund[?credit=<id>]
 *
 * Paying money back out. With `?credit=` it draws on that one credit; without,
 * on the tenant's Credit on Account as a whole (overpaid rent first, then the
 * oldest credits).
 *
 * Money leaving needs the same room as money coming in: the amount, where it
 * went and the reference all have to be right, and the summary beside the form
 * keeps the limit and the resulting balance in view while they are typed.
 */
import { ArrowLeft, Send } from "lucide-react";
import { useState } from "react";
import toast from "react-hot-toast";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { Button, Card, DatePicker, ErrorState, PageHeader, Skeleton } from "@/components/ui";
import { Note } from "@/features/credits/Note";
import { KES, METHODS, NEEDS_REFERENCE, round2 } from "@/features/credits/shared";
import { Field, inputCls } from "@/features/tenants/shared";
import { useAuth } from "@/hooks/useAuth";
import { type Refund, useCreateRefund, useCreditPosition, useTenantCredits } from "@/hooks/useCredits";
import { useTenant } from "@/hooks/useTenants";
import { getErrorMessage } from "@/lib/apiError";
import { todayIso } from "@/lib/dates";
import { formatBalanceKES } from "@/lib/money";

export default function RefundCreditPage() {
  const { id } = useParams();
  const [params] = useSearchParams();
  const creditId = params.get("credit");
  const navigate = useNavigate();
  const { user } = useAuth();

  const { data: tenant, isLoading: tenantLoading } = useTenant(id ?? null);
  const { data: position, isLoading } = useCreditPosition(id ?? null);
  const { data: credits = [] } = useTenantCredits(creditId ? id ?? null : null);
  const createRefund = useCreateRefund();

  const credit = creditId ? credits.find((c) => String(c.id) === creditId) : undefined;
  const refundable = Number(position?.refundable ?? 0);
  const limit = credit ? Math.min(Number(credit.remaining), refundable) : refundable;
  const backTo = `/tenants/${id}`;

  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState<Refund["method"]>("mpesa");
  const [paidTo, setPaidTo] = useState<string | null>(null);
  const [alreadySent, setAlreadySent] = useState(true);
  const [sentOn, setSentOn] = useState(todayIso());
  const [reference, setReference] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState("");

  const shownAmount = amount === "" && limit > 0 ? String(limit) : amount;
  const value = Number(shownAmount) || 0;
  const shownPaidTo = paidTo ?? (method === "mpesa" ? position?.tenant_phone ?? "" : "");
  const payeeDiffers =
    method === "mpesa" && !!position?.tenant_phone && shownPaidTo.trim() !== position.tenant_phone.trim();
  const balanceAfter = round2(Number(position?.balance ?? 0) + value);

  async function submit() {
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
        tenant: tenant!.id,
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
      navigate(`${backTo}#credit-history`);
    } catch (e) {
      toast.error(getErrorMessage(e, "The refund could not be recorded."));
    }
  }

  if (!user?.can_forgive_money) {
    return (
      <ErrorState
        title="Only the owner can refund a credit."
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
        title={credit ? `Refund Credit — ${credit.number}` : "Refund Credit"}
        description="Record money going back to the tenant. The books follow it on the day it leaves."
      />

      <div className="grid gap-6 lg:grid-cols-3">
        <Card padding="md" className="lg:col-span-2">
          {limit <= 0 ? (
            <>
              <Note tone="warn">
                Nothing can be refunded. Once everything the tenant owes is counted — including rent
                already invoiced for next month — they are not in credit.
              </Note>
              <div className="mt-4 flex justify-end">
                <Button variant="ghost" onClick={() => navigate(backTo)}>Back</Button>
              </div>
            </>
          ) : (
            <div className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Amount (KES) *" hint={`Up to ${KES(limit)}`}>
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

              <div className="flex justify-end gap-2 border-t border-hairline pt-4">
                <Button variant="ghost" onClick={() => navigate(backTo)}>Cancel</Button>
                <Button onClick={submit} loading={createRefund.isPending}>
                  <Send className="h-4 w-4" /> {alreadySent ? "Record Refund" : "Schedule Refund"}
                </Button>
              </div>
            </div>
          )}
        </Card>

        <Card padding="md" className="h-fit">
          <p className="text-xs uppercase tracking-wider text-content-muted">Summary</p>
          <dl className="mt-3 space-y-2 text-sm tabular-nums">
            <div className="flex justify-between gap-4">
              <dt className="text-ink-500">Can be refunded</dt>
              <dd className="font-semibold text-ink-900">{KES(limit)}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-ink-500">Drawn from</dt>
              <dd className="text-right text-ink-700">{credit ? credit.number : "Credit on Account"}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-ink-500">Refunding</dt>
              <dd className="text-ink-700">{KES(value)}</dd>
            </div>
            <div className="flex justify-between gap-4 border-t border-hairline pt-2">
              <dt className="text-ink-500">Balance after</dt>
              <dd className="font-semibold text-ink-900">
                {balanceAfter < 0 ? `${KES(-balanceAfter)} cr` : formatBalanceKES(balanceAfter)}
              </dd>
            </div>
          </dl>
          <Note>
            {alreadySent
              ? "Recorded as sent: the accounts move today and the tenant's statement shows the refund."
              : "Set aside: nothing reaches the accounts until you mark it as sent, and the amount can't be used on an invoice meanwhile."}
          </Note>
        </Card>
      </div>
    </div>
  );
}
