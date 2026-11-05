/**
 * The deposit settlement on the tenant page's Deposit card.
 *
 * Before settling: a "Settle Deposit" link, once the tenant has given notice or
 * moved out. After: the settlement's number and refund, the statement to hand
 * the tenant, and the two follow-ups — Mark Refund Sent and Void. The form
 * itself is a page (`pages/SettleDepositPage`); only these short confirmations
 * are modals, like the credit ones beside them.
 */
import { Ban, FileDown, Send, Wallet } from "lucide-react";
import { useState } from "react";
import toast from "react-hot-toast";
import { Link } from "react-router-dom";

import { Button, DatePicker, Modal } from "@/components/ui";
import { Note } from "@/features/credits/Note";
import { KES, METHODS, NEEDS_REFERENCE } from "@/features/credits/shared";
import { Field, inputCls } from "@/features/tenants/shared";
import type { Refund } from "@/hooks/useCredits";
import {
  type DepositSettlement,
  useMarkDepositRefundSent,
  useSettlementPreview,
  useVoidDepositSettlement,
} from "@/hooks/useDepositSettlements";
import { getErrorMessage } from "@/lib/apiError";
import { todayIso } from "@/lib/dates";
import { downloadPdf } from "@/lib/downloadPdf";

export function DepositSettlementLinks({ tenantId }: { tenantId: number | string }) {
  const { data: preview } = useSettlementPreview(tenantId);
  const [marking, setMarking] = useState(false);
  const [voiding, setVoiding] = useState(false);
  const settlement = preview?.settlement;

  async function downloadStatement(s: DepositSettlement) {
    try {
      await downloadPdf(`/deposit-settlements/${s.id}/statement/`, `deposit-settlement-${s.number}.pdf`);
    } catch (e) {
      toast.error(getErrorMessage(e, "Could not download the settlement statement."));
    }
  }

  if (!preview) return null;
  if (!settlement) {
    if (!preview.can_settle || Number(preview.deposit_held) <= 0) return null;
    return (
      <div className="mt-2 text-xs">
        <Link to={`/tenants/${tenantId}/deposit/settle`} className="inline-flex items-center gap-1 text-teal-700 hover:underline">
          <Wallet className="h-3 w-3" /> Settle Deposit
        </Link>
      </div>
    );
  }

  return (
    <div className="mt-2 space-y-1 text-xs">
      <p className="text-content-muted">
        Settled {settlement.number}: {KES(settlement.deductions_total)} kept,{" "}
        {settlement.refund_status === "none"
          ? "nothing to refund"
          : `${KES(settlement.refund_amount)} ${settlement.refund_status === "sent" ? "refunded" : "to refund"}`}
      </p>
      <div className="flex flex-wrap gap-x-3 gap-y-1">
        <button type="button" onClick={() => void downloadStatement(settlement)} className="inline-flex items-center gap-1 text-teal-700 hover:underline">
          <FileDown className="h-3 w-3" /> Statement
        </button>
        {settlement.refund_status === "to_send" && (
          <button type="button" onClick={() => setMarking(true)} className="inline-flex items-center gap-1 text-teal-700 hover:underline">
            <Send className="h-3 w-3" /> Mark Refund Sent
          </button>
        )}
        {settlement.refund_status !== "sent" && (
          <button type="button" onClick={() => setVoiding(true)} className="inline-flex items-center gap-1 text-content-muted hover:underline">
            <Ban className="h-3 w-3" /> Void
          </button>
        )}
      </div>
      {marking && <MarkDepositRefundSentModal settlement={settlement} onClose={() => setMarking(false)} />}
      {voiding && <VoidSettlementModal settlement={settlement} onClose={() => setVoiding(false)} />}
    </div>
  );
}

function MarkDepositRefundSentModal({ settlement, onClose }: { settlement: DepositSettlement; onClose: () => void }) {
  const markSent = useMarkDepositRefundSent();
  const [sentOn, setSentOn] = useState(todayIso());
  const [method, setMethod] = useState<Refund["method"]>(settlement.method || "mpesa");
  const [reference, setReference] = useState("");

  async function submit() {
    if (NEEDS_REFERENCE.has(method) && !reference.trim()) {
      toast.error("Enter the transaction reference of the money you sent.");
      return;
    }
    try {
      await markSent.mutateAsync({ id: settlement.id, sent_on: sentOn, method, reference: reference.trim() });
      toast.success(`${settlement.number}: deposit refund marked as sent.`);
      onClose();
    } catch (e) {
      toast.error(getErrorMessage(e, "Could not mark the refund as sent."));
    }
  }

  return (
    <Modal
      open onClose={onClose} size="sm" eyebrow={settlement.number} title="Mark Refund Sent" closeOnBackdrop={false}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button onClick={submit} loading={markSent.isPending}>Mark as Sent</Button>
        </>
      }
    >
      <p className="text-sm text-ink-700">{KES(settlement.refund_amount)} to {settlement.paid_to || "the tenant"}.</p>
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

function VoidSettlementModal({ settlement, onClose }: { settlement: DepositSettlement; onClose: () => void }) {
  const voidSettlement = useVoidDepositSettlement();
  const [reason, setReason] = useState("");

  async function submit() {
    try {
      await voidSettlement.mutateAsync({ id: settlement.id, reason: reason.trim() });
      toast.success(`${settlement.number} voided. The deposit can be settled again.`);
      onClose();
    } catch (e) {
      toast.error(getErrorMessage(e, "Could not void the settlement."));
    }
  }

  return (
    <Modal
      open onClose={onClose} size="sm" eyebrow={settlement.number} title="Void Deposit Settlement" closeOnBackdrop={false}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="danger" onClick={submit} loading={voidSettlement.isPending} disabled={!reason.trim()}>
            Void Settlement
          </Button>
        </>
      }
    >
      <Note tone="warn">
        The full {KES(settlement.deposit_held)} deposit goes back to being held.
        {settlement.credit_number && ` ${settlement.credit_number} is voided, so the rent it settled is owed again.`}
        {" "}The deductions are reversed in the books today.
      </Note>
      <div className="mt-4">
        <Field label="Reason *">
          <input value={reason} onChange={(e) => setReason(e.target.value)} className={inputCls} maxLength={255} />
        </Field>
      </div>
    </Modal>
  );
}
