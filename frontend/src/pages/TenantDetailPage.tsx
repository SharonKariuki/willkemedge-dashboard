/**
 * TenantDetailPage — /tenants/:id
 *
 * The bottom of the Property → Unit → Tenant drill-down. Shows contact info,
 * the downloadable statement, and full payment history + arrears (the history
 * that the tenant modal was missing).
 */
import { ArrowLeft, Download, Mail, Phone } from "lucide-react";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import toast from "react-hot-toast";

import {
  Badge, Breadcrumb, Button, Card, ErrorState, Skeleton,
  Table, TBody, TD, TH, THead, TR,
} from "@/components/ui";
import { usePaymentHistory, useTenant } from "@/hooks/useTenants";
import { getErrorMessage } from "@/lib/apiError";
import { downloadPdf } from "@/lib/downloadPdf";

const KES = (n: string | number) => `KES ${Number(n || 0).toLocaleString()}`;

export default function TenantDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { data: tenant, isLoading, isError, refetch } = useTenant(id ?? null);
  const { data: history } = usePaymentHistory(id ?? null);
  const [downloading, setDownloading] = useState(false);

  async function handleStatement() {
    setDownloading(true);
    try {
      await downloadPdf(`/tenants/${id}/statement-pdf/`, `Statement-${tenant?.full_name ?? id}.pdf`);
    } catch (e) {
      toast.error(getErrorMessage(e, "Could not download the statement."));
    } finally {
      setDownloading(false);
    }
  }

  if (isLoading) {
    return <div className="space-y-4">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-24" />)}</div>;
  }
  if (isError || !tenant) {
    return (
      <ErrorState
        title="Tenant could not be loaded."
        description="This is usually temporary."
        onRetry={() => void refetch()}
      />
    );
  }

  return (
    <div className="space-y-6">
      <Breadcrumb
        items={[
          { label: "Portfolio", to: "/buildings" },
          { label: tenant.building_name, to: `/buildings/${tenant.building_id}` },
          { label: tenant.full_name },
        ]}
      />

      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <button
            onClick={() => navigate(-1)}
            className="mb-2 inline-flex items-center gap-1 text-sm text-content-muted hover:text-content"
          >
            <ArrowLeft className="h-4 w-4" /> Back
          </button>
          <h1 className="font-display text-2xl font-bold text-content sm:text-3xl">{tenant.full_name}</h1>
          <p className="mt-1 text-sm text-content-muted">
            {tenant.building_name} · Unit {tenant.unit_label}
          </p>
        </div>
        <Button variant="outline" onClick={handleStatement} loading={downloading}>
          <Download className="h-4 w-4" /> Statement PDF
        </Button>
      </div>

      {/* Contact + finance summary */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card padding="md">
          <p className="text-xs uppercase tracking-wider text-content-muted">Status</p>
          <div className="mt-2">
            <Badge tone={tenant.status === "active" ? "sage" : tenant.status === "notice_given" ? "ochre" : "neutral"} withDot>
              {tenant.status_display}
            </Badge>
          </div>
        </Card>
        <Card padding="md">
          <p className="text-xs uppercase tracking-wider text-content-muted">Monthly rent</p>
          <p className="mt-2 font-semibold tabular-nums text-content">{KES(tenant.monthly_rent)}</p>
        </Card>
        <Card padding="md">
          <p className="text-xs uppercase tracking-wider text-content-muted">Total paid</p>
          <p className="mt-2 font-semibold tabular-nums text-sage-600">{KES(history?.total_paid ?? 0)}</p>
        </Card>
        <Card padding="md">
          <p className="text-xs uppercase tracking-wider text-content-muted">Arrears</p>
          <p className="mt-2 font-semibold tabular-nums text-orange-600">{KES(history?.total_arrears ?? 0)}</p>
        </Card>
      </div>

      {/* Contact */}
      <Card padding="md">
        <p className="mb-3 font-semibold text-content">Contact</p>
        <div className="flex flex-wrap gap-6 text-sm">
          <a href={`tel:${tenant.phone}`} className="inline-flex items-center gap-2 text-sage-600">
            <Phone className="h-4 w-4" /> {tenant.phone}
          </a>
          {tenant.email && (
            <a href={`mailto:${tenant.email}`} className="inline-flex items-center gap-2 text-sage-600">
              <Mail className="h-4 w-4" /> {tenant.email}
            </a>
          )}
          {tenant.id_number && <span className="text-content-muted">ID: {tenant.id_number}</span>}
          {tenant.kra_pin && <span className="text-content-muted">KRA: {tenant.kra_pin}</span>}
        </div>
      </Card>

      {/* Payment history */}
      <Card padding="none">
        <div className="border-b border-hairline px-5 py-4">
          <h2 className="font-semibold text-content">Payment history</h2>
        </div>
        {history?.payments.length ? (
          <Table>
            <THead>
              <TR><TH>Date</TH><TH>Period</TH><TH>Method</TH><TH>Reference</TH><TH className="text-right">Amount</TH></TR>
            </THead>
            <TBody>
              {history.payments.map((p) => (
                <TR key={p.id}>
                  <TD className="text-content-muted">{p.payment_date}</TD>
                  <TD>{p.period_month}/{p.period_year}</TD>
                  <TD><Badge tone="neutral">{p.source || "—"}</Badge></TD>
                  <TD className="font-mono text-xs text-content-muted">{p.reference || "—"}</TD>
                  <TD className="text-right font-medium tabular-nums text-content">{KES(p.amount)}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        ) : (
          <p className="px-5 py-6 text-sm text-content-muted">No payments recorded yet.</p>
        )}
      </Card>

      {/* Outstanding arrears */}
      {history?.arrears.length ? (
        <Card padding="none">
          <div className="border-b border-hairline px-5 py-4">
            <h2 className="font-semibold text-content">Outstanding arrears</h2>
          </div>
          <Table>
            <THead>
              <TR><TH>Period</TH><TH className="text-right">Expected</TH><TH className="text-right">Paid</TH><TH className="text-right">Balance</TH></TR>
            </THead>
            <TBody>
              {history.arrears.map((a, i) => (
                <TR key={i}>
                  <TD>{a.period}</TD>
                  <TD className="text-right tabular-nums">{KES(a.expected)}</TD>
                  <TD className="text-right tabular-nums">{KES(a.paid)}</TD>
                  <TD className="text-right font-medium tabular-nums text-orange-600">{KES(a.balance)}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </Card>
      ) : null}
    </div>
  );
}
