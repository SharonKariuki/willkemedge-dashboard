import { Check, Copy, MessageSquare, Plus, RefreshCw } from "lucide-react";
import { useState } from "react";

import { Button, Card, Modal, Skeleton } from "@/components/ui";
import { useRefreshSmsBalance, useSmsBalance, type SmsBalance } from "@/hooks/useNotifications";
import { cn } from "@/lib/cn";

/**
 * The Africa's Talking SMS wallet: what is left, and the M-Pesa paybill to
 * refill it.
 *
 * Read-only on purpose. The director wants to know when tenant reminders are
 * about to stop going out, and to have the paybill in front of him when they
 * are — the top-up itself happens on his phone. There is no STK push and no
 * stored payment instrument here, so this card can only ever show numbers.
 *
 * It appears on the dashboard (compact), on Notifications and in Settings,
 * which is why the paybill and account number come from the server rather than
 * being written into three templates that can drift apart.
 *
 * Deliberately quiet: neutral surface and a teal accent while healthy, amber
 * only once the balance drops below the server's low threshold, so the card is
 * ignorable until it needs attention.
 */

/**
 * The meter has no natural "full", so it is drawn against the one number the
 * server does define: the low threshold sits at a fixed point on the track and
 * the fill shows how far above (or below) that line the wallet is.
 */
const LOW_MARK = 0.25;

function CopyField({ label, value, grow = false }: { label: string; value: string; grow?: boolean }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard is blocked on insecure origins and in some mobile browsers.
      // The value is on screen either way, so a failed copy is not worth
      // interrupting anyone over.
    }
  };

  return (
    <button
      type="button"
      onClick={copy}
      aria-label={`Copy ${label}: ${value}`}
      className={cn(
        "group flex min-w-0 items-center justify-between gap-2 rounded-lg px-3 py-2 text-left",
        grow ? "flex-1" : "shrink-0",
        " transition-colors hover:bg-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
      )}
    >
      <span className="min-w-0">
        <span className="block text-[10px] font-semibold uppercase tracking-[0.12em] text-content-muted">
          {label}
        </span>
        <span className="block break-all font-mono text-sm font-semibold tabular-nums text-content">
          {value || "—"}
        </span>
      </span>
      <span
        aria-hidden
        className={cn(
          "flex h-6 w-6 shrink-0 items-center justify-center rounded-md transition-all",
          copied
            ? "bg-success-soft text-success"
            : "text-content-muted opacity-40 group-hover:bg-hover group-hover:opacity-100"
        )}
      >
        {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
      </span>
      <span className="sr-only" aria-live="polite">
        {copied ? `${label} copied` : ""}
      </span>
    </button>
  );
}

/** Paybill + account number, the two things needed to load airtime. */
function TopupSlip({ topup, low }: { topup: SmsBalance["topup"]; low: boolean }) {
  return (
    <div className="max-w-md">
      <p className="mb-1.5 text-[11px] font-medium text-content-muted">
        {low ? "Top up now via M-Pesa" : "Top up via M-Pesa"}
      </p>
      <div
        className={cn(
          "flex items-stretch rounded-xl p-0.5 ring-1 ring-inset",
          low ? "bg-warning-soft/60 ring-warning/20" : "bg-surface-sunk ring-border/60"
        )}
      >
        <CopyField label="Paybill" value={topup.paybill} />
        <span aria-hidden className="my-2 w-px bg-border" />
        <CopyField label="Account" value={topup.account} grow />
      </div>
    </div>
  );
}

function Meter({ balance, threshold, low }: { balance: number; threshold: number; low: boolean }) {
  if (!(threshold > 0)) return null;
  const fill = Math.min(1, Math.max(0.02, (balance / threshold) * LOW_MARK));
  return (
    <div
      className="relative mt-3 h-1 rounded-full bg-surface-sunk"
      role="img"
      aria-label={`Balance is ${low ? "below" : "above"} the low-credit line of KES ${threshold.toLocaleString()}`}
    >
      <div
        className={cn(
          "h-full rounded-full transition-[width] duration-700 ease-out",
          low ? "bg-warning" : "bg-gradient-to-r from-teal-800 to-teal-700"
        )}
        style={{ width: `${fill * 100}%` }}
      />
      {/* The low-credit line */}
      <span
        aria-hidden
        className="absolute -top-1 h-3 w-0.5 rounded-full bg-content-muted/40"
        style={{ left: `${LOW_MARK * 100}%` }}
      />
    </div>
  );
}

interface Props {
  /** Dashboard placement: tighter spacing, no note or "last checked" line. */
  compact?: boolean;
  className?: string;
}

export default function SmsBalanceCard({ compact = false, className }: Props) {
  const { data, isLoading, isFetching } = useSmsBalance();
  const refresh = useRefreshSmsBalance();

  const busy = isFetching || refresh.isPending;
  const amount = data?.balance != null ? Number(data.balance) : null;
  const low = Boolean(data?.low && amount != null);
  const threshold = Number(data?.low_threshold ?? 0);

  const [whole, fraction] =
    amount != null
      ? amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }).split(".")
      : ["", ""];

  return (
    <Card
      variant="glass"
      padding={compact ? "sm" : "md"}
      className={cn("relative overflow-hidden", className)}
    >
      {/* A faint wash of the state colour in the corner — enough to tell
          healthy from low at a glance without shouting. */}
      <div
        aria-hidden
        className={cn(
          "pointer-events-none absolute -right-16 -top-16 h-40 w-40 rounded-full blur-3xl",
          low ? "bg-warning/15" : "bg-teal-700/10"
        )}
      />

      {isLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-8 w-40" />
          <Skeleton className="h-14" />
        </div>
      ) : (
        <div className="relative">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-content-muted">
                SMS credit
              </p>
              {amount != null && (
                <span
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium",
                    low ? "bg-warning-soft text-warning" : "bg-teal-700/10 text-teal-800 dark:text-teal-600"
                  )}
                >
                  <span className="relative flex h-1.5 w-1.5">
                    {low && (
                      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-warning opacity-60 motion-reduce:hidden" />
                    )}
                    <span className={cn("relative h-1.5 w-1.5 rounded-full", low ? "bg-warning" : "bg-teal-700")} />
                  </span>
                  {low ? "Low" : "Healthy"}
                </span>
              )}
            </div>
            <button
              type="button"
              onClick={() => refresh.mutate()}
              disabled={busy}
              aria-label={busy ? "Checking SMS balance" : "Refresh SMS balance"}
              title="Refresh"
              className="-mr-1.5 rounded-lg p-1.5 text-content-muted transition-colors hover:bg-hover hover:text-content focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40 disabled:opacity-60"
            >
              <RefreshCw className={cn("h-3.5 w-3.5", busy && "animate-spin")} />
            </button>
          </div>

          {amount != null ? (
            <>
              <p className="mt-2 flex items-baseline gap-1.5 tabular-nums text-content">
                <span className="text-sm font-medium text-content-muted">{data?.currency || "KES"}</span>
                <span
                  className={cn(
                    "font-semibold leading-none tracking-tight",
                    compact ? "text-[28px]" : "text-[34px]"
                  )}
                >
                  {whole}
                  <span className="text-[0.55em] font-medium text-content-muted">.{fraction}</span>
                </span>
              </p>

              <Meter balance={amount} threshold={threshold} low={low} />

              <p className="mt-2 text-xs text-content-secondary">
                {data?.sms_remaining != null && (
                  <>
                    <span className="font-semibold tabular-nums text-content">
                      ≈ {data.sms_remaining.toLocaleString()}
                    </span>{" "}
                    messages left
                  </>
                )}
                {low && (
                  <span className="text-content-muted">
                    {data?.sms_remaining != null ? " · " : ""}
                    below KES {threshold.toLocaleString()}, reminders may stop
                  </span>
                )}
              </p>
            </>
          ) : (
            <p className="mt-2 text-sm text-content-secondary">
              {data?.error ?? "Balance unavailable right now."}
            </p>
          )}

          {data?.topup && (
            <div className={compact ? "mt-4" : "mt-5"}>
              <TopupSlip topup={data.topup} low={low} />
            </div>
          )}

          {!compact && (data?.topup?.note || data?.checked_at) && (
            <p className="mt-3 text-[11px] leading-relaxed text-content-muted">
              {data?.topup?.note}
              {data?.topup?.note && data?.checked_at && " · "}
              {data?.checked_at && (
                <>
                  Checked {new Date(data.checked_at).toLocaleString()}
                  {data.cached && " (cached)"}
                </>
              )}
            </p>
          )}
        </div>
      )}
    </Card>
  );
}

/**
 * The dashboard's account widget: the balance at a glance and a Top up button
 * that opens the meter and the paybill slip. The full card lives on
 * Notifications and in Settings.
 */
export function SmsCreditWidget({ className }: { className?: string }) {
  const { data, isLoading, isFetching } = useSmsBalance();
  const refresh = useRefreshSmsBalance();
  const [open, setOpen] = useState(false);

  const busy = isFetching || refresh.isPending;
  const amount = data?.balance != null ? Number(data.balance) : null;
  const low = Boolean(data?.low && amount != null);
  const threshold = Number(data?.low_threshold ?? 0);
  const money =
    amount != null
      ? `${data?.currency || "KES"} ${amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
      : null;

  return (
    <>
      <div
        className={cn(
          "flex items-center gap-3 rounded-2xl border bg-surface py-2 pl-2.5 pr-2 shadow-sm",
          low ? "border-warning/40" : "border-border",
          className
        )}
      >
        <span
          className={cn(
            "flex h-9 w-9 shrink-0 items-center justify-center rounded-xl",
            low ? "bg-warning-soft text-warning" : "bg-teal-700/10 text-teal-800 dark:text-teal-600"
          )}
        >
          <MessageSquare className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-content-muted">
            SMS credit{low && <span className="ml-1.5 text-warning">· Low</span>}
          </p>
          {isLoading ? (
            <Skeleton className="mt-1 h-4 w-24" />
          ) : (
            <p
              className={cn(
                "truncate text-sm font-semibold tabular-nums",
                money == null ? "text-content-muted" : low ? "text-warning" : "text-content"
              )}
            >
              {money ?? "Unavailable"}
              {data?.sms_remaining != null && (
                <span className="font-normal text-content-muted"> · ≈ {data.sms_remaining.toLocaleString()} SMS</span>
              )}
            </p>
          )}
        </div>
        <Button size="sm" variant="secondary" className="rounded-xl" onClick={() => setOpen(true)}>
          <Plus className="h-3.5 w-3.5" />
          Top up
        </Button>
      </div>

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Top up SMS credit"
        size="sm"
        headerActions={
          <Button
            size="icon-sm"
            variant="ghost"
            onClick={() => refresh.mutate()}
            disabled={busy}
            aria-label={busy ? "Checking SMS balance" : "Refresh SMS balance"}
          >
            <RefreshCw className={cn("h-3.5 w-3.5", busy && "animate-spin")} />
          </Button>
        }
      >
        <div className="space-y-5">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-content-muted">Balance</p>
            <p className={cn("mt-1 text-2xl font-semibold tabular-nums", low ? "text-warning" : "text-content")}>
              {money ?? "Unavailable"}
            </p>
            {amount != null && <Meter balance={amount} threshold={threshold} low={low} />}
            <p className="mt-2 text-xs text-content-secondary">
              {data?.sms_remaining != null && <>≈ {data.sms_remaining.toLocaleString()} messages left</>}
              {low && <> · below KES {threshold.toLocaleString()}, reminders may stop</>}
              {amount == null && (data?.error ?? "Balance unavailable right now.")}
            </p>
          </div>
          {data?.topup && <TopupSlip topup={data.topup} low={low} />}
          {data?.topup?.note && <p className="text-[11px] leading-relaxed text-content-muted">{data.topup.note}</p>}
        </div>
      </Modal>
    </>
  );
}
