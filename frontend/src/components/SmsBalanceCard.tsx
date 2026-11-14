import { Check, ChevronRight, Copy, MessageSquare, Plus, RefreshCw } from "lucide-react";
import { useState, type ReactNode } from "react";

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
 * Deliberately quiet: neutral surface and a teal accent while healthy, red
 * only once the balance drops below the server's low threshold, so the card is
 * ignorable until it needs attention.
 */

/**
 * The meter has no natural "full", so it is drawn against the one number the
 * server does define: the low threshold sits a quarter of the way along, and
 * the fill shows how far above (or below) that line the wallet is.
 */
const LOW_MARK = 0.25;

function useCopy(value: string) {
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
  return { copied, copy };
}

/** One value to type into M-Pesa, with its own copy button. */
function CopyTile({ label, value }: { label: string; value: string }) {
  const { copied, copy } = useCopy(value);
  return (
    <div className="mt-2 flex items-center justify-between gap-3 rounded-xl border border-border bg-surface-sunk py-2 pl-3.5 pr-2">
      <span className="min-w-0 break-all text-base font-semibold tabular-nums tracking-wide text-content">
        {value || "—"}
      </span>
      <button
        type="button"
        onClick={copy}
        aria-label={`Copy ${label}: ${value}`}
        className={cn(
          "inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-3 text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40 focus-visible:ring-offset-1",
          copied
            ? "bg-success-soft text-success"
            : "bg-teal-700 text-white shadow-sm hover:bg-teal-800"
        )}
      >
        {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
        {copied ? "Copied" : "Copy"}
      </button>
      <span className="sr-only" aria-live="polite">
        {copied ? `${label} copied` : ""}
      </span>
    </div>
  );
}

function Step({ n, title, last = false, children }: { n: number; title: string; last?: boolean; children?: ReactNode }) {
  return (
    <li className={cn("relative flex gap-3", !last && "pb-5")}>
      {/* The rail joining the step numbers */}
      {!last && <span aria-hidden className="absolute bottom-1 left-3 top-8 w-px bg-border" />}
      <span className="relative flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-teal-700/10 text-xs font-semibold tabular-nums text-teal-800 dark:text-teal-600">
        {n}
      </span>
      <div className="min-w-0 flex-1 pt-0.5">
        <p className="text-sm font-medium leading-5 text-content">{title}</p>
        {children}
      </div>
    </li>
  );
}

function Crumb({ children }: { children: ReactNode }) {
  return (
    <span className="rounded-md border border-border bg-surface-sunk px-2 py-0.5 text-xs font-medium text-content-secondary">
      {children}
    </span>
  );
}

/** How to load airtime: the M-Pesa menu path, then the two numbers to type. */
function TopupSteps({ topup }: { topup: SmsBalance["topup"] }) {
  return (
    <ol className="max-w-md">
      <Step n={1} title="Open M-Pesa">
        <p className="mt-2 flex flex-wrap items-center gap-1.5">
          <Crumb>Lipa na M-Pesa</Crumb>
          <ChevronRight aria-hidden className="h-3.5 w-3.5 text-content-muted" />
          <Crumb>Pay Bill</Crumb>
        </p>
      </Step>
      <Step n={2} title="Enter business number">
        <CopyTile label="business number" value={topup.paybill} />
      </Step>
      <Step n={3} title="Enter account number" last>
        <CopyTile label="account number" value={topup.account} />
      </Step>
    </ol>
  );
}

function LowPill() {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-danger-soft px-2 py-0.5 text-[11px] font-semibold normal-case tracking-normal text-danger">
      <span className="h-1.5 w-1.5 rounded-full bg-danger" />
      Low balance
    </span>
  );
}

function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-content-muted">{children}</p>
  );
}

function Meter({ balance, threshold, low }: { balance: number; threshold: number; low: boolean }) {
  if (!(threshold > 0)) return null;
  const fill = Math.min(1, Math.max(0.03, (balance / threshold) * LOW_MARK));
  return (
    <div
      className="h-2 overflow-hidden rounded-full bg-surface-sunk"
      role="img"
      aria-label={`Balance is ${low ? "below" : "above"} the low-credit line of KES ${threshold.toLocaleString()}`}
    >
      <div
        className={cn(
          "h-full rounded-full transition-[width] duration-700 ease-out",
          low ? "bg-danger" : "bg-teal-700"
        )}
        style={{ width: `${fill * 100}%` }}
      />
    </div>
  );
}

/** "KES 2,340.50" in the bold slate of the rest of the money on screen. */
function Money({ amount, currency, className }: { amount: number; currency?: string; className?: string }) {
  return (
    <p className={cn("font-bold leading-none tracking-tight tabular-nums text-content", className)}>
      <span className="mr-1.5 text-[0.5em] font-semibold text-content-muted">{currency || "KES"}</span>
      {amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
    </p>
  );
}

const FOOTNOTE = "Credits reflect instantly after payment confirmation.";

interface Props {
  /** Tighter spacing, no footnote or "last checked" line. */
  compact?: boolean;
  className?: string;
}

function RefreshButton({ busy, onClick }: { busy: boolean; onClick: () => void }) {
  return (
    <Button
      size="icon-sm"
      variant="ghost"
      onClick={onClick}
      disabled={busy}
      aria-label={busy ? "Checking SMS balance" : "Refresh SMS balance"}
      title="Refresh"
    >
      <RefreshCw className={cn("h-3.5 w-3.5", busy && "animate-spin")} />
    </Button>
  );
}

/** Balance, meter and message estimate — the top half of both views. */
function BalanceBlock({ data, size }: { data: SmsBalance | undefined; size: "md" | "lg" }) {
  const amount = data?.balance != null ? Number(data.balance) : null;
  const low = Boolean(data?.low && amount != null);
  if (amount == null) {
    return <p className="text-sm text-content-secondary">{data?.error ?? "Balance unavailable right now."}</p>;
  }
  return (
    <div>
      <div className="flex items-end justify-between gap-3">
        <Money amount={amount} currency={data?.currency} className={size === "lg" ? "text-[34px]" : "text-3xl"} />
        {data?.sms_remaining != null && (
          <p className="pb-0.5 text-xs text-content-muted">
            <span className="font-semibold tabular-nums text-content-secondary">
              ≈ {data.sms_remaining.toLocaleString()}
            </span>{" "}
            SMS left
          </p>
        )}
      </div>
      <div className="mt-4">
        <Meter balance={amount} threshold={Number(data?.low_threshold ?? 0)} low={low} />
      </div>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-content-muted">{label}</dt>
      <dd className="mt-0.5 truncate font-semibold tabular-nums text-content">{value}</dd>
    </div>
  );
}

/**
 * The full wallet card, on Notifications and in Settings: balance, meter and
 * the top-up steps all on show.
 */
export default function SmsBalanceCard({ compact = false, className }: Props) {
  const { data, isLoading, isFetching } = useSmsBalance();
  const refresh = useRefreshSmsBalance();

  const busy = isFetching || refresh.isPending;
  const low = Boolean(data?.low && data?.balance != null);

  return (
    <Card variant="glass" padding={compact ? "sm" : "md"} className={className}>
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <SectionLabel>SMS credit</SectionLabel>
          {low && <LowPill />}
        </div>
        <RefreshButton busy={busy} onClick={() => refresh.mutate()} />
      </div>

      {isLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-8 w-40" />
          <Skeleton className="h-2" />
        </div>
      ) : (
        <div className="grid gap-6 md:grid-cols-[minmax(0,1fr)_minmax(0,28rem)] md:gap-10">
          <div>
            <SectionLabel>Current balance</SectionLabel>
            <div className="mt-3">
              <BalanceBlock data={data} size="lg" />
            </div>
            {!compact && (
              <dl className="mt-6 grid grid-cols-3 gap-4 text-xs">
                <Fact label="Low-credit line" value={`KES ${Number(data?.low_threshold ?? 0).toLocaleString()}`} />
                <Fact label="Cost per SMS" value={`KES ${data?.unit_cost ?? "—"}`} />
                <Fact
                  label="Last checked"
                  value={
                    data?.checked_at
                      ? new Date(data.checked_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
                      : "—"
                  }
                />
              </dl>
            )}
          </div>
          {data?.topup && (
            <div className="border-t border-border pt-5 md:border-l md:border-t-0 md:pl-10 md:pt-0">
              <SectionLabel>How to top up</SectionLabel>
              <div className="mt-4">
                <TopupSteps topup={data.topup} />
              </div>
            </div>
          )}
        </div>
      )}

      {!compact && !isLoading && (
        <p className="mt-5 border-t border-border pt-3 text-xs text-content-muted">
          {FOOTNOTE}
        </p>
      )}
    </Card>
  );
}

/**
 * The dashboard's account widget: the balance at a glance and a Top up button
 * that opens the meter and the top-up steps. The full card lives on
 * Notifications and in Settings.
 */
export function SmsCreditWidget({ className }: { className?: string }) {
  const { data, isLoading, isFetching } = useSmsBalance();
  const refresh = useRefreshSmsBalance();
  const [open, setOpen] = useState(false);

  const busy = isFetching || refresh.isPending;
  const amount = data?.balance != null ? Number(data.balance) : null;
  const low = Boolean(data?.low && amount != null);

  return (
    <>
      <div
        className={cn(
          "flex items-center gap-3 rounded-2xl border border-border bg-surface py-2 pl-2 pr-2",
          className
        )}
      >
        {/* Navy at rest; only the "Low" tag turns red, so the masthead beside the
            greeting does not read as an alarm. */}
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-navy-800/[0.07] text-navy-700 dark:bg-navy-500/15 dark:text-navy-500">
          <MessageSquare className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <SectionLabel>SMS credit</SectionLabel>
            {low && (
              <span className="rounded bg-danger-soft px-1.5 py-px text-[10px] font-semibold uppercase tracking-wider text-danger">
                Low
              </span>
            )}
          </div>
          {isLoading ? (
            <Skeleton className="mt-1 h-4 w-24" />
          ) : (
            <p className="truncate text-sm font-bold tabular-nums text-content">
              {amount != null ? (
                `${data?.currency || "KES"} ${amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
              ) : (
                <span className="font-medium text-content-muted">Unavailable</span>
              )}
              {data?.sms_remaining != null && (
                <span className="font-normal text-content-muted"> · ≈ {data.sms_remaining.toLocaleString()} SMS</span>
              )}
            </p>
          )}
        </div>
        <Button size="sm" variant="primary" className="rounded-xl" onClick={() => setOpen(true)}>
          <Plus className="h-3.5 w-3.5" />
          Top up
        </Button>
      </div>

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        size="sm"
        ariaLabel="Top up SMS credit"
        title={
          <span className="flex flex-wrap items-center gap-2.5">
            Top up SMS credit
            {low && <LowPill />}
          </span>
        }
        headerActions={<RefreshButton busy={busy} onClick={() => refresh.mutate()} />}
      >
        <div className="space-y-6">
          <section>
            <div className="mb-3">
              <SectionLabel>Current balance</SectionLabel>
            </div>
            <BalanceBlock data={data} size="md" />
          </section>

          {data?.topup && (
            <section className="border-t border-border pt-6">
              <div className="mb-4">
                <SectionLabel>How to top up</SectionLabel>
              </div>
              <TopupSteps topup={data.topup} />
            </section>
          )}

          <p className="flex items-center gap-2 rounded-lg bg-surface-sunk px-3 py-2.5 text-xs text-content-secondary">
            <Check aria-hidden className="h-3.5 w-3.5 shrink-0 text-success" />
            {FOOTNOTE}
          </p>
        </div>
      </Modal>
    </>
  );
}
