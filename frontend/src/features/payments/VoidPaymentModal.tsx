import { AlertTriangle, Undo2 } from "lucide-react";
import { useState } from "react";
import toast from "react-hot-toast";

import { Button, Modal, Skeleton } from "@/components/ui";
import { type Payment, useVoidPayment, useVoidPreview } from "@/hooks/usePayments";
import { getErrorMessage } from "@/lib/apiError";

const inputCls =
  "w-full rounded-md bg-surface-raised hairline px-3 py-2.5 text-sm text-ink-900 placeholder:text-ink-400 focus:outline-none focus:ring-2 focus:ring-sage-500/40";

const money = (value: string | number) => `KES ${Number(value).toLocaleString()}`;

function PaymentLine({ payment, muted }: { payment: Payment; muted?: boolean }) {
  return (
    <li className="flex items-baseline justify-between gap-3 tabular-nums">
      <span className={muted ? "text-ink-500" : "text-ink-900"}>
        {payment.period_month}/{payment.period_year}
        {muted ? "" : " · this row"}
      </span>
      <span className={muted ? "text-ink-500" : "font-medium text-ink-900"}>
        {money(payment.amount)}
      </span>
    </li>
  );
}

/**
 * Confirmation for unwinding a payment.
 *
 * Deliberately not a plain "are you sure": one bank credit is often several
 * Payment rows, and voiding just the clicked row leaves the rest of the money
 * on the tenant's account. So the dialog fetches the group first and shows
 * what will actually be reversed before offering the button.
 */
export function VoidPaymentModal({
  payment,
  onClose,
}: {
  payment: Payment;
  onClose: () => void;
}) {
  const [reason, setReason] = useState("");
  const [scope, setScope] = useState<"reference" | "single">("reference");

  const { data: preview, isLoading, isError } = useVoidPreview(payment.id);
  const voidPayment = useVoidPayment();

  const siblings = preview?.siblings ?? [];
  const isSplit = siblings.length > 0;
  const willVoid = scope === "single" ? 1 : siblings.length + 1;
  const willTotal =
    scope === "single" ? payment.amount : (preview?.total ?? payment.amount);

  const handleVoid = async () => {
    const trimmed = reason.trim();
    if (!trimmed) {
      toast.error("Give a reason — it goes on the audit record.");
      return;
    }
    try {
      const result = await voidPayment.mutateAsync({
        id: payment.id,
        reason: trimmed,
        scope,
      });
      toast.success(
        result.voided_count > 1
          ? `Voided ${result.voided_count} payments (${money(willTotal)})`
          : `Voided ${money(willTotal)}`,
      );
      onClose();
    } catch (e) {
      toast.error(getErrorMessage(e, "Failed to void payment"));
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      size="sm"
      eyebrow="Correction"
      title="Void payment"
      closeOnBackdrop={false}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button
            variant="danger"
            onClick={handleVoid}
            loading={voidPayment.isPending}
            disabled={isLoading || isError || !reason.trim()}
          >
            <Undo2 className="h-4 w-4" />
            Void {willVoid > 1 ? `${willVoid} payments` : money(willTotal)}
          </Button>
        </>
      }
    >
      <p className="-mt-1 text-sm text-ink-900">
        <span className="font-medium">{payment.tenant_name}</span>
        <span className="text-ink-500">
          {" "}· {payment.building_name} · {payment.unit_label}
        </span>
      </p>
      <p className="mt-1 text-xs text-ink-500">
        {money(payment.amount)} on {payment.payment_date}
        {payment.reference ? ` · ref ${payment.reference}` : " · no reference"}
      </p>

      {isLoading ? (
        <Skeleton className="mt-4 h-20" />
      ) : isError ? (
        <p className="mt-4 rounded-md bg-danger-soft px-3 py-2.5 text-xs text-danger">
          Could not check whether this credit was split across several
          payments. Close and retry rather than voiding blind.
        </p>
      ) : isSplit ? (
        <div className="mt-4 rounded-md bg-warning-soft px-3 py-3">
          <p className="flex items-center gap-1.5 text-xs font-medium text-warning">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
            This credit was split across {siblings.length + 1} payments
          </p>
          <p className="mt-1.5 text-[11px] text-ink-500">
            Reference {payment.reference} settled more than one period. Voiding
            only the row you clicked would leave the rest of the money on the
            tenant&apos;s account.
          </p>
          <ul className="mt-2.5 space-y-1 border-t border-ink-200/70 pt-2.5 text-xs">
            <PaymentLine payment={payment} />
            {siblings.map((s) => (
              <PaymentLine key={s.id} payment={s} muted />
            ))}
          </ul>

          <fieldset className="mt-3 space-y-1.5 border-t border-ink-200/70 pt-2.5">
            <legend className="sr-only">How much to void</legend>
            <label className="flex items-start gap-2 text-xs text-ink-900">
              <input
                type="radio"
                name="void-scope"
                value="reference"
                checked={scope === "reference"}
                onChange={() => setScope("reference")}
                className="mt-0.5"
              />
              <span>
                Void the whole credit — all {siblings.length + 1} rows,{" "}
                {money(preview?.total ?? payment.amount)}
              </span>
            </label>
            <label className="flex items-start gap-2 text-xs text-ink-900">
              <input
                type="radio"
                name="void-scope"
                value="single"
                checked={scope === "single"}
                onChange={() => setScope("single")}
                className="mt-0.5"
              />
              <span>
                Void this row only — {payment.period_month}/{payment.period_year},{" "}
                {money(payment.amount)}
              </span>
            </label>
          </fieldset>
        </div>
      ) : null}

      <label
        htmlFor="void-reason"
        className="mb-1 mt-4 block text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500"
      >
        Reason *
      </label>
      <textarea
        id="void-reason"
        rows={2}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        placeholder="e.g. paid to the wrong unit — re-recording under B12"
        className={inputCls}
      />
      <p className="mt-2 text-[11px] leading-relaxed text-ink-500">
        Nothing is deleted. The payment is marked void, a mirror-image reversal
        is posted to the ledger and the period&apos;s arrears are re-derived.
        The original row stays on the books for audit, against your name.
        {" "}If this money belongs to another tenant, record it against them
        afterwards.
      </p>
    </Modal>
  );
}
