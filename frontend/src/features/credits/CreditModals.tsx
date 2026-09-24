/**
 * The owner's credit and refund confirmations.
 *
 * Only the short ones live here — Mark as Sent, Void Credit, Cancel/Void
 * Refund — because each is a single decision taken from a row in Credit
 * History. The two real forms, Add Credit and Refund Credit, are pages
 * (`pages/AddCreditPage`, `pages/RefundCreditPage`): they carry enough fields,
 * and enough consequence, to deserve the room and a URL of their own.
 */
import { Ban, Undo2 } from "lucide-react";
import { useMemo, useState } from "react";
import toast from "react-hot-toast";

import { Button, DatePicker, Modal, Skeleton } from "@/components/ui";
import { Note } from "@/features/credits/Note";
import { KES, METHODS, NEEDS_REFERENCE } from "@/features/credits/shared";
import { Field, inputCls } from "@/features/tenants/shared";
import {
  type Refund,
  type TenantCredit,
  useCloseRefund,
  useMarkRefundSent,
  useVoidCredit,
  useVoidCreditPreview,
} from "@/hooks/useCredits";
import { getErrorMessage } from "@/lib/apiError";
import { todayIso } from "@/lib/dates";

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
