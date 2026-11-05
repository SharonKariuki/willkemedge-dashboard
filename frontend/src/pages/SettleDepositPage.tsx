/**
 * SettleDepositPage — /tenants/:id/deposit/settle
 *
 * What happens to the security deposit when a tenant leaves. The owner lists
 * what is kept back — the unpaid balance, damages, cleaning, anything else —
 * and states the refund as whatever is left, a fixed amount or a percentage
 * of the deposit. Every shilling has to be accounted for: the summary keeps
 * "Not accounted for" in view and the page will not settle until it is zero.
 *
 * The result is a numbered settlement (DS-…) with a statement for the tenant.
 */
import { ArrowLeft, Plus, Trash2, Wallet } from "lucide-react";
import { useState } from "react";
import toast from "react-hot-toast";
import { Link, useNavigate, useParams } from "react-router-dom";

import { Button, Card, DatePicker, ErrorState, PageHeader, Skeleton } from "@/components/ui";
import { Note } from "@/features/credits/Note";
import { KES, METHODS, NEEDS_REFERENCE, refundFor, round2 } from "@/features/credits/shared";
import { Field, inputCls } from "@/features/tenants/shared";
import { useAuth } from "@/hooks/useAuth";
import type { Refund } from "@/hooks/useCredits";
import {
  type DeductionKind,
  type RefundBasis,
  useSettleDeposit,
  useSettlementPreview,
} from "@/hooks/useDepositSettlements";
import { useTenant } from "@/hooks/useTenants";
import { getErrorMessage } from "@/lib/apiError";
import { todayIso } from "@/lib/dates";

const KINDS: { value: DeductionKind; label: string }[] = [
  { value: "unpaid_balance", label: "Unpaid rent and charges" },
  { value: "damages", label: "Damages and repairs" },
  { value: "cleaning", label: "Cleaning" },
  { value: "other", label: "Other" },
];

const BASES: { value: RefundBasis; label: string }[] = [
  { value: "remainder", label: "Whatever is left after the deductions" },
  { value: "amount", label: "A fixed amount" },
  { value: "percentage", label: "A percentage of the deposit" },
];

interface Line {
  key: number;
  kind: DeductionKind;
  description: string;
  amount: string;
  category: number | null;
}

let nextKey = 1;

export default function SettleDepositPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const { data: tenant, isLoading: tenantLoading } = useTenant(id ?? null);
  const { data: preview, isLoading } = useSettlementPreview(id ?? null);
  const settle = useSettleDeposit();
  const backTo = `/tenants/${id}`;

  const held = Number(preview?.deposit_held ?? 0);
  const owed = Number(preview?.balance_owed ?? 0);

  const [date, setDate] = useState(todayIso());
  // Starts with the unpaid balance already on the list: it is the first thing
  // a deposit settles, and the figure is the system's, not the owner's.
  const [lines, setLines] = useState<Line[] | null>(null);
  const shownLines: Line[] = lines ?? (owed > 0 && held > 0
    ? [{ key: 0, kind: "unpaid_balance", description: "", amount: String(Math.min(owed, held)), category: null }]
    : []);
  const [basis, setBasis] = useState<RefundBasis>("remainder");
  const [refundAmount, setRefundAmount] = useState("");
  const [refundPct, setRefundPct] = useState("");
  const [method, setMethod] = useState<Refund["method"]>("mpesa");
  const [paidTo, setPaidTo] = useState<string | null>(null);
  const [alreadySent, setAlreadySent] = useState(false);
  const [sentOn, setSentOn] = useState(todayIso());
  const [reference, setReference] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState("");

  const deductions = round2(shownLines.reduce((sum, l) => sum + (Number(l.amount) || 0), 0));
  const refund = refundFor(basis, held, deductions, refundAmount, refundPct);
  const unaccounted = round2(held - deductions - refund);
  const refundShare = held > 0 ? round2((refund / held) * 100) : 0;
  const shownPaidTo = paidTo ?? (method === "mpesa" ? preview?.tenant_phone ?? "" : "");
  const hasUnpaid = shownLines.some((l) => l.kind === "unpaid_balance");

  const categoryFor = (kind: DeductionKind) => preview?.default_categories?.[kind] ?? null;

  function update(key: number, patch: Partial<Line>) {
    setLines(shownLines.map((l) => (l.key === key ? { ...l, ...patch } : l)));
  }

  function add(kind: DeductionKind) {
    const amount = kind === "unpaid_balance" ? String(Math.max(Math.min(owed, held - deductions), 0)) : "";
    setLines([...shownLines, { key: nextKey++, kind, description: "", amount, category: categoryFor(kind) }]);
  }

  function changeKind(line: Line, kind: DeductionKind) {
    update(line.key, { kind, category: kind === "unpaid_balance" ? null : line.category ?? categoryFor(kind) });
  }

  function problem(): string {
    for (const l of shownLines) {
      if (!(Number(l.amount) > 0)) return "Enter an amount for every deduction, or remove the empty line.";
      if (l.kind !== "unpaid_balance" && !l.category) return "Choose the cost each damages, cleaning or other deduction recovers.";
    }
    const unpaid = shownLines.filter((l) => l.kind === "unpaid_balance");
    if (unpaid.length > 1) return "Enter the unpaid balance as one line.";
    if (unpaid.length && Number(unpaid[0].amount) > owed) return `The tenant owes ${KES(owed)}; the deposit cannot settle more than that.`;
    if (deductions > held) return `The deductions come to more than the ${KES(held)} deposit.`;
    if (basis === "percentage" && !(Number(refundPct) >= 0 && Number(refundPct) <= 100 && refundPct !== "")) {
      return "Enter a percentage between 0 and 100.";
    }
    if (basis === "amount" && refundAmount === "") return "Enter the amount to refund.";
    if (refund < 0) return "The refund cannot be less than zero.";
    if (unaccounted > 0) return `${KES(unaccounted)} of the deposit is not accounted for. Itemise it as a deduction, or refund it.`;
    if (unaccounted < 0) return `The refund and the deductions come to ${KES(-unaccounted)} more than the deposit.`;
    if (refund > 0 && alreadySent && NEEDS_REFERENCE.has(method) && !reference.trim()) {
      return "Enter the transaction reference of the refund you sent.";
    }
    return "";
  }

  async function submit() {
    const p = problem();
    setError(p);
    if (p) return;
    try {
      const s = await settle.mutateAsync({
        tenant: tenant!.id,
        settlement_date: date,
        deductions: shownLines.map((l) => ({
          kind: l.kind, description: l.description.trim(), amount: Number(l.amount).toFixed(2),
          expense_category: l.kind === "unpaid_balance" ? null : l.category,
        })),
        refund_basis: basis,
        refund_amount: basis === "amount" ? Number(refundAmount).toFixed(2) : null,
        refund_percentage: basis === "percentage" ? refundPct : null,
        method: refund > 0 ? method : "",
        paid_to: refund > 0 ? shownPaidTo.trim() : "",
        reference: reference.trim(),
        already_sent: refund > 0 && alreadySent,
        sent_on: refund > 0 && alreadySent ? sentOn : null,
        notes: notes.trim(),
      });
      toast.success(`${s.number}: deposit settled — ${KES(s.refund_amount)} to refund.`);
      navigate(`${backTo}#deposit`);
    } catch (e) {
      toast.error(getErrorMessage(e, "The deposit could not be settled."));
    }
  }

  if (!user?.can_forgive_money) {
    return (
      <ErrorState
        title="Only the owner can settle a deposit."
        description="Settling a deposit keeps or pays out money owed back to the tenant."
      />
    );
  }
  if (isLoading || tenantLoading || !preview || !tenant) {
    return <div className="space-y-4">{Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-40" />)}</div>;
  }

  const blocked = !preview.can_settle
    ? "Record the tenant's move-out notice or move-out first."
    : preview.settlement
      ? `This deposit was settled on ${preview.settlement.number}. Void it from the tenant page to redo it.`
      : held <= 0
        ? "There is no deposit on the books to settle."
        : "";

  return (
    <div className="space-y-6">
      <div>
        <Link to={backTo} className="mb-2 inline-flex items-center gap-1 text-sm text-content-muted hover:text-content">
          <ArrowLeft className="h-4 w-4" /> Back to {tenant.full_name}
        </Link>
        <PageHeader className="mb-0" eyebrow={`${tenant.building_name} · Unit ${tenant.unit_label}`} title="Settle Deposit" />
      </div>

      <Card variant="glass" padding="md" className="animate-fade-up">
        {blocked ? (
          <>
            <Note tone="warn">{blocked}</Note>
            <div className="mt-4 flex justify-end">
              <Button variant="ghost" onClick={() => navigate(backTo)}>Back</Button>
            </div>
          </>
        ) : (
          <div className="space-y-6">
            <div className="grid gap-4 sm:grid-cols-3">
              <div>
                <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">Deposit held</p>
                <p className="mt-1 text-lg font-semibold tabular-nums text-ink-900">{KES(held)}</p>
              </div>
              <div>
                <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">Tenant owes</p>
                <p className="mt-1 text-lg font-semibold tabular-nums text-ink-900">{KES(owed)}</p>
              </div>
              <DatePicker label="Settlement date *" value={date} onChange={(e) => setDate(e.target.value)} />
            </div>

            <section className="space-y-3">
              <h2 className="text-sm font-semibold text-ink-900">Deductions</h2>
              {shownLines.length === 0 && (
                <p className="text-sm text-ink-500">Nothing kept back — the whole deposit is refunded unless you add a deduction.</p>
              )}
              {shownLines.map((line) => (
                <div key={line.key} className="grid gap-3 rounded-md border border-hairline p-3 sm:grid-cols-[12rem_1fr_9rem_auto] sm:items-end">
                  <Field label="For">
                    <select
                      aria-label="Deduction type"
                      value={line.kind}
                      onChange={(e) => changeKind(line, e.target.value as DeductionKind)}
                      className={inputCls}
                    >
                      {KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
                    </select>
                  </Field>
                  <Field label="Description (printed for the tenant)">
                    <input
                      value={line.description}
                      onChange={(e) => update(line.key, { description: e.target.value })}
                      className={inputCls}
                      maxLength={200}
                      placeholder={KINDS.find((k) => k.value === line.kind)?.label}
                    />
                  </Field>
                  <Field label="Amount (KES)">
                    <input
                      aria-label="Deduction amount"
                      inputMode="decimal"
                      value={line.amount}
                      onChange={(e) => update(line.key, { amount: e.target.value })}
                      className={inputCls}
                    />
                  </Field>
                  <Button variant="ghost" size="sm" aria-label="Remove deduction" onClick={() => setLines(shownLines.filter((l) => l.key !== line.key))}>
                    <Trash2 className="h-4 w-4" />
                  </Button>
                  {line.kind !== "unpaid_balance" && (
                    <div className="sm:col-span-4">
                      <Field label="Cost it recovers" hint="The expense this deduction pays back, e.g. the repair it covers.">
                        <select
                          value={line.category ?? ""}
                          onChange={(e) => update(line.key, { category: e.target.value ? Number(e.target.value) : null })}
                          className={inputCls}
                        >
                          <option value="">Choose…</option>
                          {preview.expense_categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                        </select>
                      </Field>
                    </div>
                  )}
                </div>
              ))}
              <div className="flex flex-wrap gap-2">
                {!hasUnpaid && owed > 0 && (
                  <Button variant="ghost" size="sm" onClick={() => add("unpaid_balance")}><Plus className="h-3.5 w-3.5" /> Unpaid rent</Button>
                )}
                <Button variant="ghost" size="sm" onClick={() => add("damages")}><Plus className="h-3.5 w-3.5" /> Damages</Button>
                <Button variant="ghost" size="sm" onClick={() => add("cleaning")}><Plus className="h-3.5 w-3.5" /> Cleaning</Button>
                <Button variant="ghost" size="sm" onClick={() => add("other")}><Plus className="h-3.5 w-3.5" /> Other</Button>
              </div>
              {hasUnpaid && (
                <Note>The unpaid balance is settled on the tenant&apos;s account as a credit, oldest rent first, and shows on their statement.</Note>
              )}
            </section>

            <section className="space-y-3">
              <h2 className="text-sm font-semibold text-ink-900">Refund</h2>
              <fieldset className="space-y-1.5">
                <legend className="sr-only">How is the refund stated?</legend>
                {BASES.map((b) => (
                  <label key={b.value} className="flex items-center gap-2 text-sm">
                    <input type="radio" name="basis" checked={basis === b.value} onChange={() => setBasis(b.value)} />
                    {b.label}
                  </label>
                ))}
              </fieldset>
              {basis === "amount" && (
                <Field label="Refund amount (KES) *" hint={`Up to ${KES(held)}`}>
                  <input inputMode="decimal" value={refundAmount} onChange={(e) => setRefundAmount(e.target.value)} className={inputCls} />
                </Field>
              )}
              {basis === "percentage" && (
                <Field label="Percentage of the deposit to refund *" hint={refundPct !== "" ? `= ${KES(refund)}` : undefined}>
                  <input inputMode="decimal" value={refundPct} onChange={(e) => setRefundPct(e.target.value)} className={inputCls} placeholder="e.g. 75" />
                </Field>
              )}

              {refund > 0 && (
                <>
                  <div className="grid gap-4 sm:grid-cols-2">
                    <Field label="Method *">
                      <select value={method} onChange={(e) => setMethod(e.target.value as Refund["method"])} className={inputCls}>
                        {METHODS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
                      </select>
                    </Field>
                    <Field label="Paid to" hint={method === "bank" ? "Bank and account number." : "Phone number."}>
                      <input value={shownPaidTo} onChange={(e) => setPaidTo(e.target.value)} className={inputCls} />
                    </Field>
                  </div>
                  <fieldset className="space-y-1.5">
                    <legend className="mb-1 text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">
                      Has the refund already been sent?
                    </legend>
                    <label className="flex items-center gap-2 text-sm">
                      <input type="radio" name="sent" checked={!alreadySent} onChange={() => setAlreadySent(false)} />
                      No, I&apos;ll send it later
                    </label>
                    <label className="flex items-center gap-2 text-sm">
                      <input type="radio" name="sent" checked={alreadySent} onChange={() => setAlreadySent(true)} />
                      Yes — record it now
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
                </>
              )}
            </section>

            <Field label="Notes (printed on the settlement statement)">
              <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} className={inputCls} />
            </Field>

            <dl className="grid gap-x-8 gap-y-2 rounded-md bg-surface-sunk px-4 py-3 text-sm tabular-nums sm:grid-cols-4" aria-label="Settlement summary">
              <div className="flex justify-between gap-4 sm:block">
                <dt className="text-ink-500">Deposit held</dt>
                <dd className="font-semibold text-ink-900">{KES(held)}</dd>
              </div>
              <div className="flex justify-between gap-4 sm:block">
                <dt className="text-ink-500">Deductions</dt>
                <dd className="text-ink-700">{KES(deductions)}</dd>
              </div>
              <div className="flex justify-between gap-4 sm:block">
                <dt className="text-ink-500">Refund</dt>
                <dd className="font-semibold text-ink-900">{KES(refund)}{held > 0 && ` (${refundShare}%)`}</dd>
              </div>
              <div className="flex justify-between gap-4 sm:block">
                <dt className="text-ink-500">Not accounted for</dt>
                <dd className={unaccounted === 0 ? "text-ink-700" : "font-semibold text-warning"}>{KES(unaccounted)}</dd>
              </div>
            </dl>
            {owed > 0 && (
              <Note>
                {hasUnpaid
                  ? `After settling, the tenant will owe ${KES(Math.max(owed - Number(shownLines.find((l) => l.kind === "unpaid_balance")?.amount || 0), 0))}.`
                  : `The tenant owes ${KES(owed)} and none of it is being taken from the deposit.`}
              </Note>
            )}

            {error && <Note tone="warn">{error}</Note>}

            <div className="flex justify-end gap-2 border-t border-hairline pt-4">
              <Button variant="ghost" onClick={() => navigate(backTo)}>Cancel</Button>
              <Button onClick={submit} loading={settle.isPending}>
                <Wallet className="h-4 w-4" /> Settle Deposit
              </Button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
