/**
 * BuildingDetailPage — /buildings/:id
 *
 * Middle of the Property → Unit → Tenant drill-down: the unit list for one
 * property. Occupied units link to the tenant detail page; vacant units are
 * shown but inert.
 */
import { ArrowLeft, DoorOpen } from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";

import {
  Badge, Breadcrumb, Card, EmptyState, ErrorState, Skeleton,
  Table, TBody, TD, TH, THead, TR,
} from "@/components/ui";
import { useBuilding } from "@/hooks/useBuildings";
import { useTenants } from "@/hooks/useTenants";

const KES = (n: string | number) => `KES ${Number(n || 0).toLocaleString()}`;

export default function BuildingDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { data: building, isLoading, isError, refetch } = useBuilding(id ?? "");
  const { data: tenants } = useTenants(id ? { building: id } : undefined);

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

  // Map each unit label to its active tenant (if any) for the drill-down link.
  const tenantByUnit = new Map((tenants ?? []).map((t) => [t.unit_label, t]));
  const units = building.units ?? [];
  const occupied = units.filter((u) => tenantByUnit.has(u.label)).length;

  return (
    <div className="space-y-6">
      <Breadcrumb items={[{ label: "Portfolio", to: "/buildings" }, { label: building.name }]} />

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
                          {KES(tenant.balance)}
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
    </div>
  );
}
