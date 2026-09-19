/**
 * Credits — the tenant page's record of every credit and refund on the account.
 *
 * Each credit row opens onto its Credit History: who added it and why, where it
 * was applied, what was refunded, and any void. Nothing is ever removed from
 * this list; a voided credit stays, struck through, with the reason.
 */
import { ChevronDown, ChevronRight, FileText, Pause, Play, Plus, Send, Undo2 } from "lucide-react";
import { Fragment, useState } from "react";
import toast from "react-hot-toast";

import { Badge, Button, Card, Table, TBody, TD, TH, THead, TR } from "@/components/ui";
import {
  type Refund,
  type TenantCredit,
  useHoldCredit,
  useTenantCredits,
  useTenantRefunds,
} from "@/hooks/useCredits";
import { api } from "@/lib/api";
import { getErrorMessage } from "@/lib/apiError";
import { cn } from "@/lib/cn";
import { toDayFirst } from "@/lib/dates";
import { formatKES } from "@/lib/money";

import {
  AddCreditModal,
  CloseRefundModal,
  MarkRefundSentModal,
  RefundCreditModal,
  VoidCreditModal,
} from "./CreditModals";

const KES = formatKES;

const STATUS_TONE: Record<TenantCredit["status_display"], "paid" | "partial" | "neutral" | "info" | "unpaid"> = {
  Available: "paid",
  "Partly used": "info",
  Held: "partial",
  "Fully used": "neutral",
  Void: "unpaid",
};

const REFUND_TONE: Record<Refund["status"], "paid" | "partial" | "neutral" | "unpaid"> = {
  sent: "paid",
  scheduled: "partial",
  cancelled: "neutral",
  void: "unpaid",
};

async function openEvidence(credit: TenantCredit) {
  try {
    const { data } = await api.get<Blob>(`/tenant-credits/${credit.id}/evidence/`, { responseType: "blob" });
    const url = URL.createObjectURL(data);
    window.open(url, "_blank", "noopener");
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  } catch (e) {
    toast.error(getErrorMessage(e, "Could not open the document."));
  }
}

function CreditHistory({ credit }: { credit: TenantCredit }) {
  return (
    <div className="space-y-3 bg-surface-sunk px-5 py-4 text-sm">
      <p className="text-ink-900">&ldquo;{credit.description}&rdquo;</p>
      <dl className="grid gap-x-6 gap-y-1 text-xs text-ink-600 sm:grid-cols-2">
        {credit.corrects && <div><dt className="inline text-ink-500">Corrects: </dt><dd className="inline">{credit.corrects}</dd></div>}
        {credit.expense_category_name && <div><dt className="inline text-ink-500">Cost: </dt><dd className="inline">{credit.expense_category_name}</dd></div>}
        {Number(credit.vat_amount) > 0 && (
          <div><dt className="inline text-ink-500">Includes VAT: </dt><dd className="inline">{KES(credit.vat_amount)}</dd></div>
        )}
        {credit.reference && <div><dt className="inline text-ink-500">Reference: </dt><dd className="inline">{credit.reference}</dd></div>}
        {credit.internal_notes && <div className="sm:col-span-2"><dt className="inline text-ink-500">Internal note: </dt><dd className="inline">{credit.internal_notes}</dd></div>}
        <div>
          <dt className="inline text-ink-500">Approved: </dt>
          <dd className="inline">
            {credit.approved_by_name || "—"}{credit.approval_mode === "owner_self" ? " (owner, sole approver)" : ""}
          </dd>
        </div>
      </dl>
      {credit.has_evidence && (
        <button type="button" onClick={() => void openEvidence(credit)} className="inline-flex items-center gap-1 text-xs text-teal-700 underline">
          <FileText className="h-3.5 w-3.5" /> {credit.evidence_name || "Supporting document"}
        </button>
      )}
      <ol className="space-y-1.5 border-l border-ink-200 pl-4">
        {credit.history.map((event, i) => (
          <li key={`${event.kind}-${i}`} className="flex flex-wrap items-baseline justify-between gap-2 text-xs">
            <span className={cn("text-ink-700", event.kind === "void" && "text-danger")}>
              <span className="text-ink-500">{toDayFirst(event.date)}</span> · {event.text}
            </span>
            <span className="tabular-nums text-ink-900">{KES(event.amount)}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

export function CreditsPanel({
  tenantId, tenantName, canManage,
}: {
  tenantId: number;
  tenantName: string;
  canManage: boolean;
}) {
  const { data: credits = [] } = useTenantCredits(tenantId);
  const { data: refunds = [] } = useTenantRefunds(tenantId);
  const holdCredit = useHoldCredit();

  const [open, setOpen] = useState<number | null>(null);
  const [adding, setAdding] = useState(false);
  const [refunding, setRefunding] = useState<TenantCredit | null>(null);
  const [voiding, setVoiding] = useState<TenantCredit | null>(null);
  const [sending, setSending] = useState<Refund | null>(null);
  const [closing, setClosing] = useState<{ refund: Refund; action: "cancel" | "void" } | null>(null);

  async function toggleHold(credit: TenantCredit) {
    try {
      const updated = await holdCredit.mutateAsync({ id: credit.id, hold: !credit.on_hold });
      toast.success(
        updated.on_hold
          ? `${credit.number} is held — it won't be applied automatically.`
          : `${credit.number} will apply to the next invoice.`,
      );
    } catch (e) {
      toast.error(getErrorMessage(e, "Could not update the credit."));
    }
  }

  return (
    <Card padding="none" id="credit-history">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-hairline px-5 py-4">
        <div>
          <h2 className="font-semibold text-content">Credits &amp; refunds</h2>
          <p className="text-xs text-content-muted">Credit History — every credit added, applied, refunded or voided.</p>
        </div>
        {canManage && (
          <Button variant="outline" size="sm" onClick={() => setAdding(true)}>
            <Plus className="h-4 w-4" /> Add Credit
          </Button>
        )}
      </div>

      {credits.length ? (
        <Table minWidth={860}>
          <THead>
            <TR>
              <TH className="w-8" />
              <TH>No.</TH><TH>Date</TH><TH>Reason</TH>
              <TH className="text-right">Amount</TH><TH className="text-right">Used</TH>
              <TH className="text-right">Available</TH><TH>Status</TH>
              {canManage && <TH className="text-right">Actions</TH>}
            </TR>
          </THead>
          <TBody>
            {credits.map((credit) => {
              const expanded = open === credit.id;
              const used = Number(credit.amount_applied) + Number(credit.amount_refunded);
              const usable = !credit.is_void && Number(credit.remaining) > 0;
              return (
                <Fragment key={credit.id}>
                  <TR className={cn(credit.is_void && "text-content-muted line-through decoration-ink-300")}>
                    <TD>
                      <button
                        type="button"
                        aria-label={expanded ? "Hide credit history" : "Show credit history"}
                        onClick={() => setOpen(expanded ? null : credit.id)}
                        className="text-ink-500 hover:text-ink-900"
                      >
                        {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                      </button>
                    </TD>
                    <TD className="font-mono text-xs">{credit.number}</TD>
                    <TD className="whitespace-nowrap text-content-muted">{toDayFirst(credit.credit_date)}</TD>
                    <TD>{credit.reason_display}</TD>
                    <TD className="text-right tabular-nums">{KES(credit.amount)}</TD>
                    <TD className="text-right tabular-nums text-content-muted">{used ? KES(used) : "—"}</TD>
                    <TD className="text-right font-medium tabular-nums">{credit.is_void ? "—" : KES(credit.remaining)}</TD>
                    <TD><Badge tone={STATUS_TONE[credit.status_display]}>{credit.status_display}</Badge></TD>
                    {canManage && (
                      <TD className="text-right">
                        <div className="flex justify-end gap-1 no-underline">
                          {usable && (
                            <>
                              <Button
                                variant="ghost" size="sm"
                                onClick={() => void toggleHold(credit)}
                                title={credit.on_hold ? "Apply to Next Invoice" : "Hold Credit"}
                              >
                                {credit.on_hold
                                  ? <><Play className="h-3.5 w-3.5" /> Apply to Next Invoice</>
                                  : <><Pause className="h-3.5 w-3.5" /> Hold</>}
                              </Button>
                              <Button variant="ghost" size="sm" onClick={() => setRefunding(credit)}>
                                <Send className="h-3.5 w-3.5" /> Refund
                              </Button>
                            </>
                          )}
                          {!credit.is_void && (
                            <Button variant="ghost" size="sm" onClick={() => setVoiding(credit)}>
                              <Undo2 className="h-3.5 w-3.5" /> Void
                            </Button>
                          )}
                        </div>
                      </TD>
                    )}
                  </TR>
                  {expanded && (
                    <TR>
                      <TD colSpan={canManage ? 9 : 8} className="p-0">
                        <CreditHistory credit={credit} />
                      </TD>
                    </TR>
                  )}
                </Fragment>
              );
            })}
          </TBody>
        </Table>
      ) : (
        <p className="px-5 py-6 text-sm text-content-muted">
          No credits added. Overpaid rent is carried forward automatically and shows in the balance.
        </p>
      )}

      {refunds.length > 0 && (
        <div className="border-t border-hairline">
          <p className="px-5 pb-1 pt-4 text-xs font-medium uppercase tracking-[0.14em] text-content-muted">Refunds</p>
          <Table minWidth={760}>
            <THead>
              <TR>
                <TH>No.</TH><TH>Sent</TH><TH>Method</TH><TH>Reference</TH><TH>From</TH>
                <TH className="text-right">Amount</TH><TH>Status</TH>
                {canManage && <TH className="text-right">Actions</TH>}
              </TR>
            </THead>
            <TBody>
              {refunds.map((refund) => (
                <TR key={refund.id} className={cn(refund.status === "void" && "text-content-muted line-through")}>
                  <TD className="font-mono text-xs">{refund.number}</TD>
                  <TD className="whitespace-nowrap text-content-muted">{refund.sent_on ? toDayFirst(refund.sent_on) : "—"}</TD>
                  <TD>{refund.method_display}</TD>
                  <TD className="font-mono text-xs text-content-muted">{refund.reference || "—"}</TD>
                  <TD className="text-xs text-content-muted">{refund.lines.map((l) => l.source).join(", ")}</TD>
                  <TD className="text-right tabular-nums">{KES(refund.amount)}</TD>
                  <TD><Badge tone={REFUND_TONE[refund.status]}>{refund.status_display}</Badge></TD>
                  {canManage && (
                    <TD className="text-right">
                      <div className="flex justify-end gap-1 no-underline">
                        {refund.status === "scheduled" && (
                          <>
                            <Button variant="ghost" size="sm" onClick={() => setSending(refund)}>Mark as Sent</Button>
                            <Button variant="ghost" size="sm" onClick={() => setClosing({ refund, action: "cancel" })}>Cancel</Button>
                          </>
                        )}
                        {refund.status === "sent" && (
                          <Button variant="ghost" size="sm" onClick={() => setClosing({ refund, action: "void" })}>Void</Button>
                        )}
                      </div>
                    </TD>
                  )}
                </TR>
              ))}
            </TBody>
          </Table>
        </div>
      )}

      {adding && <AddCreditModal tenantId={tenantId} tenantName={tenantName} onClose={() => setAdding(false)} />}
      {refunding && (
        <RefundCreditModal tenantId={tenantId} tenantName={tenantName} credit={refunding} onClose={() => setRefunding(null)} />
      )}
      {voiding && <VoidCreditModal credit={voiding} tenantName={tenantName} onClose={() => setVoiding(null)} />}
      {sending && <MarkRefundSentModal refund={sending} onClose={() => setSending(null)} />}
      {closing && <CloseRefundModal refund={closing.refund} action={closing.action} onClose={() => setClosing(null)} />}
    </Card>
  );
}
