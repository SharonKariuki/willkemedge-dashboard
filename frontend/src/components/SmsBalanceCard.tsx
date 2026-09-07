import { AlertTriangle, Check, Copy, MessageSquare, RefreshCw } from "lucide-react";
import { useState } from "react";

import { Badge, Button, Card, CardHeader, CardTitle, Skeleton } from "@/components/ui";
import { useSmsBalance, type SmsBalance } from "@/hooks/useNotifications";
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
 */

function CopyValue({ label, value }: { label: string; value: string }) {
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
      className="group inline-flex items-center gap-1.5 rounded px-1 py-0.5 font-mono text-sm font-semibold text-ink-900 transition-colors hover:bg-white/60"
    >
      {value || "—"}
      {copied ? (
        <Check className="h-3.5 w-3.5 text-sage-600" />
      ) : (
        <Copy className="h-3.5 w-3.5 text-ink-500 opacity-0 transition-opacity group-hover:opacity-100" />
      )}
    </button>
  );
}

/** Paybill + account number, the two things needed to load airtime. */
function TopupDetails({ topup, compact }: { topup: SmsBalance["topup"]; compact: boolean }) {
  return (
    <div className={cn("rounded-lg border border-gray-200/70", compact ? "p-2.5" : "p-3")}>
      <p className="mb-1.5 text-xs font-medium uppercase tracking-wider text-ink-500">
        Top up by M-Pesa
      </p>
      <dl className="flex flex-wrap items-center gap-x-6 gap-y-1">
        <div className="flex items-center gap-2">
          <dt className="text-sm text-ink-500">Paybill</dt>
          <dd><CopyValue label="paybill" value={topup.paybill} /></dd>
        </div>
        <div className="flex items-center gap-2">
          <dt className="text-sm text-ink-500">Account</dt>
          <dd><CopyValue label="account number" value={topup.account} /></dd>
        </div>
      </dl>
      {!compact && <p className="mt-2 text-xs text-ink-500">{topup.note}</p>}
    </div>
  );
}

interface Props {
  /** Dashboard placement: tighter spacing, no "last checked" footnote. */
  compact?: boolean;
  className?: string;
}

export default function SmsBalanceCard({ compact = false, className }: Props) {
  const { data, isLoading, isFetching, refetch } = useSmsBalance();

  const amount = data?.balance != null ? Number(data.balance) : null;

  return (
    <Card variant="glass" padding="md" className={className}>
      <CardHeader>
        <div className="flex items-center gap-2">
          <MessageSquare className="h-4 w-4 text-sage-600" />
          <CardTitle>SMS credit</CardTitle>
        </div>
        <div className="flex items-center gap-2">
          {data?.low && <Badge tone="unpaid" withDot>Running low</Badge>}
          <Button size="sm" variant="glass" onClick={() => refetch()} disabled={isFetching}>
            <RefreshCw className={cn("h-3.5 w-3.5", isFetching && "animate-spin")} />
            {isFetching ? "Checking…" : "Refresh"}
          </Button>
        </div>
      </CardHeader>

      {isLoading ? (
        <Skeleton className="h-24" />
      ) : (
        <>
          <div className={compact ? "mb-3" : "mb-4"}>
            {amount != null ? (
              <>
                <p
                  className={cn(
                    "font-semibold tabular-nums",
                    compact ? "text-2xl" : "text-3xl",
                    data?.low ? "text-orange-600" : "text-ink-900"
                  )}
                >
                  {data?.currency ?? "KES"}{" "}
                  {amount.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                </p>
                <p className="mt-1 text-sm text-ink-500">
                  {data?.sms_remaining != null
                    ? `About ${data.sms_remaining.toLocaleString()} more tenant messages at KES ${data.unit_cost} each.`
                    : "Africa's Talking account balance."}
                </p>
              </>
            ) : (
              <div className="flex items-start gap-2 rounded-md bg-orange-500/10 p-3">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-orange-600" />
                <p className="text-sm text-ink-700">
                  {data?.error ?? "The SMS balance is unavailable right now."}
                </p>
              </div>
            )}
          </div>

          {data?.low && amount != null && (
            <p
              className={cn(
                "rounded-md bg-orange-500/10 p-3 text-sm text-ink-700",
                compact ? "mb-3" : "mb-4"
              )}
            >
              Below KES {Number(data.low_threshold).toLocaleString()} — top up so rent reminders,
              receipts and statements keep going out.
            </p>
          )}

          {data?.topup && <TopupDetails topup={data.topup} compact={compact} />}

          {!compact && data?.checked_at && (
            <p className="mt-3 text-xs text-ink-500">
              Last checked {new Date(data.checked_at).toLocaleString()}
              {data.cached && " (cached)"}
            </p>
          )}
        </>
      )}
    </Card>
  );
}
