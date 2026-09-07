import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Check, Copy, MessageSquare, RefreshCw } from "lucide-react";
import { useState } from "react";

import { Badge, Button, Card, CardHeader, CardTitle, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";

/**
 * The Africa's Talking SMS wallet.
 *
 * Read-only on purpose: the director wants to know when tenant reminders are
 * about to stop going out, and to have the M-Pesa paybill in front of him when
 * they are. Loading the airtime happens on his phone — there is no STK push and
 * no payment instrument stored here, so this card can only ever show numbers.
 */
interface SmsBalance {
  configured: boolean;
  /** Decimal string, or null when the lookup failed — never coerce to 0. */
  balance: string | null;
  currency: string;
  sms_remaining: number | null;
  unit_cost: string;
  low: boolean;
  low_threshold: string;
  checked_at: string;
  cached: boolean;
  error: string | null;
  topup: { paybill: string; account: string; note: string };
}

function useSmsBalance() {
  return useQuery<SmsBalance>({
    queryKey: ["sms-balance"],
    queryFn: async () => {
      const { data } = await api.get<SmsBalance>("/notifications/sms-balance/");
      return data;
    },
    // The server already caches for a minute; this keeps a tab that stays open
    // from re-asking on every window focus.
    staleTime: 60_000,
  });
}

function CopyField({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard is blocked on insecure origins and in some mobile browsers —
      // the value is on screen either way, so a failed copy is not an error
      // worth interrupting anyone over.
    }
  };

  return (
    <div className="flex items-center justify-between gap-3 rounded-md bg-white/40 p-3 dark:bg-white/5">
      <dt className="text-sm text-ink-500">{label}</dt>
      <dd className="flex items-center gap-2">
        <span className="font-mono text-sm font-semibold text-ink-900">{value || "—"}</span>
        {value && (
          <button
            type="button"
            onClick={copy}
            aria-label={`Copy ${label}`}
            className="rounded p-1 text-ink-500 transition-colors hover:bg-white/60 hover:text-ink-900"
          >
            {copied ? <Check className="h-3.5 w-3.5 text-sage-600" /> : <Copy className="h-3.5 w-3.5" />}
          </button>
        )}
      </dd>
    </div>
  );
}

export default function SmsBalanceCard() {
  const { data, isLoading, isFetching, refetch } = useSmsBalance();

  const amount = data?.balance != null ? Number(data.balance) : null;

  return (
    <Card variant="glass" padding="md">
      <CardHeader>
        <div className="flex items-center gap-2">
          <MessageSquare className="h-4 w-4 text-sage-600" />
          <CardTitle>SMS credit</CardTitle>
        </div>
        <div className="flex items-center gap-2">
          {data?.low && <Badge tone="unpaid" withDot>Running low</Badge>}
          <Button size="sm" variant="glass" onClick={() => refetch()} disabled={isFetching}>
            <RefreshCw className={`h-3.5 w-3.5 ${isFetching ? "animate-spin" : ""}`} />
            {isFetching ? "Checking…" : "Refresh"}
          </Button>
        </div>
      </CardHeader>

      {isLoading ? (
        <Skeleton className="h-24" />
      ) : (
        <>
          <div className="mb-4">
            {amount != null ? (
              <>
                <p className="text-3xl font-semibold tabular-nums text-ink-900">
                  {data?.currency ?? "KES"} {amount.toLocaleString(undefined, { maximumFractionDigits: 2 })}
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
            <p className="mb-4 rounded-md bg-orange-500/10 p-3 text-sm text-ink-700">
              Below KES {Number(data.low_threshold).toLocaleString()} — top up so rent reminders and
              payment receipts keep going out.
            </p>
          )}

          <div className="rounded-lg border border-gray-200/70 p-3">
            <p className="mb-2 text-xs font-medium uppercase tracking-wider text-ink-500">
              Top up by M-Pesa
            </p>
            <dl className="space-y-2">
              <CopyField label="Paybill" value={data?.topup.paybill ?? ""} />
              <CopyField label="Account number" value={data?.topup.account ?? ""} />
            </dl>
            <p className="mt-2 text-xs text-ink-500">{data?.topup.note}</p>
          </div>

          {data?.checked_at && (
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
