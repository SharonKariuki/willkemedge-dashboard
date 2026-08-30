/**
 * BuildingDetailPage — /buildings/:id
 *
 * Middle of the Property → Unit → Tenant drill-down: the unit list for one
 * property. Occupied units link to the tenant detail page; vacant units are
 * shown but inert. Also the one place to email every current tenant in this
 * property their rent statement in one go.
 */
import { ArrowLeft, DoorOpen, Mail } from "lucide-react";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import {
  Badge, Button, Card, EmptyState, ErrorState, Skeleton,
  Table, TBody, TD, TH, THead, TR,
} from "@/components/ui";
import { EmailStatementsModal } from "@/features/tenants/shared";
import { useBuilding } from "@/hooks/useBuildings";
import { useTenants } from "@/hooks/useTenants";
import { formatBalanceKES, formatKES } from "@/lib/money";

const KES = formatKES;

export default function BuildingDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { data: building, isLoading, isError, refetch } = useBuilding(id ?? "");
  const { data: tenants } = useTenants(id ? { building: id } : undefined);
  const [sendingStatements, setSendingStatements] = useState(false);

  if (isLoading) {
    return <div className="space-y-4">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-20" />)}</div>;
  }
  if (isError || !building) {
    return (
      <ErrorState
        title="Property could not be loaded."
        description="This is usually temporary."
        onRetry={() => void refetch()}
      />
    );
  }

  // Map each unit label to its CURRENT occupant. The tenants endpoint returns
  // moved-out/archived tenants too, and a unit label is reused across tenancies,
  // so exclude non-current tenants — otherwise a moved-out record can overwrite
  // the active one (or make a vacated unit look occupied).
  const tenantByUnit = new Map(
    (tenants ?? [])
      .filter((t) => t.status === "active" || t.status === "notice_given")
      .map((t) => [t.unit_label, t]),
  );
  const units = building.units ?? [];
  const occupied = units.filter((u) => tenantByUnit.has(u.label)).length;

  // Everyone in this property who can actually be written to. Sourced from the
  // same current-occupant map as the table, so the button sends to exactly the
  // tenants named on screen — never to a former one whose record still returns
  // from the tenants endpoint.
  const statementRecipients = [...tenantByUnit.values()].filter((t) => Boolean(t.email));
  const withoutEmail = tenantByUnit.size - statementRecipients.length;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <button
            onClick={() => navigate("/buildings")}
            className="mb-2 inline-flex items-center gap-1 text-sm text-content-muted hover:text-content"
          >
            <ArrowLeft className="h-4 w-4" /> All properties
          </button>
          <h1 className="font-display text-2xl font-bold text-content sm:text-3xl">{building.name}</h1>
          <p className="mt-1 text-sm text-content-muted">
            {units.length} units · {occupied} occupied · {units.length - occupied} vacant
            {building.property_type_display ? ` · ${building.property_type_display}` : ""}
          </p>
        </div>
        <div className="text-right">
          <Button
            variant="outline"
            onClick={() => setSendingStatements(true)}
            disabled={statementRecipients.length === 0}
            title={statementRecipients.length === 0
              ? "No current tenant in this property has an email address on file"
              : `Email a statement to ${statementRecipients.length} tenant(s) in this property`}
          >
            <Mail className="h-4 w-4" />
            Email statements
            {statementRecipients.length > 0 ? ` (${statementRecipients.length})` : ""}
          </Button>
          {withoutEmail > 0 && (
            // Say what the button cannot reach. A count on its own reads as
            // "everyone", and the gap is the whole roster today.
            <p className="mt-1.5 text-[11px] text-content-muted">
              {withoutEmail} tenant{withoutEmail === 1 ? " has" : "s have"} no email on file
            </p>
          )}
        </div>
      </div>

      {units.length === 0 ? (
        <EmptyState icon={<DoorOpen className="h-5 w-5" />} title="No units" description="This property has no units yet." />
      ) : (
        <Card padding="none">
          <Table>
            <THead>
              <TR>
                <TH>Unit</TH><TH>Type</TH><TH>Tenant</TH>
                <TH className="text-right">Rent</TH><TH className="text-right">Balance</TH><TH>Status</TH>
              </TR>
            </THead>
            <TBody>
              {units.map((u) => {
                const tenant = tenantByUnit.get(u.label);
                return (
                  <TR
                    key={u.id}
                    className={tenant ? "cursor-pointer hover:bg-surface-sunk/60" : ""}
                    role={tenant ? "button" : undefined}
                    tabIndex={tenant ? 0 : undefined}
                    aria-label={tenant ? `View ${tenant.full_name}` : undefined}
                    onClick={tenant ? () => navigate(`/tenants/${tenant.id}`) : undefined}
                    onKeyDown={
                      tenant
                        ? (e) => {
                            if (e.key === "Enter" || e.key === " ") {
                              e.preventDefault();
                              navigate(`/tenants/${tenant.id}`);
                            }
                          }
                        : undefined
                    }
                  >
                    <TD className="font-medium text-content">{u.label}</TD>
                    <TD className="text-content-muted">{u.classification_display}</TD>
                    <TD>{tenant ? tenant.full_name : <span className="text-content-muted">Vacant</span>}</TD>
                    <TD className="text-right tabular-nums">{KES(u.monthly_rent)}</TD>
                    <TD className="text-right tabular-nums">
                      {tenant ? (
                        <span className={tenant.payment_status === "in_arrears" ? "text-orange-600" : "text-sage-600"}>
                          {formatBalanceKES(tenant.balance)}
                        </span>
                      ) : "—"}
                    </TD>
                    <TD>
                      <Badge tone={u.status === "vacant" ? "neutral" : "sage"} withDot>{u.status_display}</Badge>
                    </TD>
                  </TR>
                );
              })}
            </TBody>
          </Table>
        </Card>
      )}

      {sendingStatements && (
        <EmailStatementsModal
          tenants={statementRecipients}
          scopeLabel={`Every current tenant in ${building.name}`}
          onClose={() => setSendingStatements(false)}
          onSent={() => setSendingStatements(false)}
        />
      )}
    </div>
  );
}
