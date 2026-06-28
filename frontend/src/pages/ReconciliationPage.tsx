import { Scale } from "lucide-react";
import { useMemo, useState } from "react";
import toast from "react-hot-toast";

import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  PageHeader,
  Skeleton,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "@/components/ui";
import { useTenants } from "@/hooks/useTenants";
import {
  useAssignCredit,
  useUnmatchedCredits,
  type UnmatchedCredit,
} from "@/hooks/useUnmatchedCredits";
import { getErrorMessage } from "@/lib/apiError";

const inputCls =
  "w-full rounded-md bg-surface-raised hairline px-3 py-2 text-sm text-ink-900 focus:outline-none focus:ring-2 focus:ring-sage-500/40";

function formatKes(amount: string): string {
  const n = Number(amount);
  return Number.isFinite(n) ? `KES ${n.toLocaleString("en-KE")}` : `KES ${amount}`;
}

interface TenantOption {
  id: number;
  label: string;
}

function CreditRow({
  credit,
  tenants,
}: {
  credit: UnmatchedCredit;
  tenants: TenantOption[];
}) {
  const [tenantId, setTenantId] = useState<string>("");
  const assign = useAssignCredit();

  const handleAssign = () => {
    if (!tenantId) {
      toast.error("Pick a tenant to assign this credit to.");
      return;
    }
    assign.mutate(
      { id: credit.id, tenant: Number(tenantId) },
      {
        onSuccess: (res) => toast.success(res.detail),
        onError: (err) => toast.error(getErrorMessage(err)),
      },
    );
  };

  const hint = [credit.payer_hint.name, credit.payer_hint.phone].filter(Boolean).join(" · ");

  return (
    <TR>
      <TD className="font-medium text-ink-900">
        {formatKes(credit.amount)}
        <p className="text-[11px] font-normal text-ink-400">{credit.transaction_id}</p>
      </TD>
      <TD className="text-ink-500">
        <Badge tone="neutral">{credit.channel || "bank"}</Badge>
      </TD>
      <TD className="max-w-xs">
        <p className="truncate text-[11px] text-ink-500">{credit.narration || "—"}</p>
        {hint && <p className="truncate text-[11px] text-ink-400">Payer: {hint}</p>}
        {credit.detail && (
          <p className="truncate text-[11px] text-status-unpaid">{credit.detail}</p>
        )}
      </TD>
      <TD className="text-[11px] text-ink-400">
        {new Date(credit.received_at).toLocaleString()}
      </TD>
      <TD>
        <div className="flex items-center gap-2">
          <select
            className={inputCls}
            value={tenantId}
            onChange={(e) => setTenantId(e.target.value)}
            disabled={assign.isPending}
            aria-label={`Assign credit ${credit.transaction_id} to tenant`}
          >
            <option value="">Select tenant…</option>
            {tenants.map((t) => (
              <option key={t.id} value={t.id}>
                {t.label}
              </option>
            ))}
          </select>
          <Button onClick={handleAssign} disabled={assign.isPending || !tenantId}>
            {assign.isPending ? "Assigning…" : "Assign"}
          </Button>
        </div>
      </TD>
    </TR>
  );
}

export default function ReconciliationPage() {
  const { data: credits, isLoading, isError, refetch } = useUnmatchedCredits();
  const { data: tenants } = useTenants({ status: "active" });

  const tenantOptions: TenantOption[] = useMemo(
    () =>
      (tenants ?? []).map((t) => ({
        id: t.id,
        label: t.unit_label ? `${t.unit_label} — ${t.full_name}` : t.full_name,
      })),
    [tenants],
  );

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Payments"
        title="Reconciliation"
        description="Bank credits we couldn't automatically match to a tenant. Assign each one to record the payment."
      />

      <Card className="p-5">
        {isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-12" />
            ))}
          </div>
        ) : isError ? (
          <ErrorState
            title="Unmatched credits could not be loaded."
            description="The reconciliation queue did not come back. This is usually temporary."
            onRetry={() => void refetch()}
          />
        ) : !credits?.length ? (
          <EmptyState
            icon={<Scale className="h-5 w-5" />}
            title="Nothing to reconcile"
            description="Every bank credit has been matched to a tenant. New unmatched credits will appear here."
          />
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <THead>
                <TR>
                  <TH>Amount</TH>
                  <TH>Channel</TH>
                  <TH>Narration / Reason</TH>
                  <TH>Received</TH>
                  <TH>Assign to tenant</TH>
                </TR>
              </THead>
              <TBody>
                {credits.map((credit) => (
                  <CreditRow key={credit.id} credit={credit} tenants={tenantOptions} />
                ))}
              </TBody>
            </Table>
          </div>
        )}
      </Card>
    </div>
  );
}
