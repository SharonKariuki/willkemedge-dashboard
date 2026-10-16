/**
 * Space — the units a commercial tenancy occupies.
 *
 * A tenant can take several units in one property and pay for them as one
 * space (a hospital across MCG05–MCG08). The units need not be next to each
 * other or on the same floor — only vacant, commercial and in this building. The tenancy stays on its own unit; the others
 * are added to or taken out of its space here, and the rent moves with them —
 * by each unit's standing rent unless a different figure has been agreed. The
 * new rent is billed from the next billing run; months already charged stand.
 */
import { Layers, Minus, Plus } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import toast from "react-hot-toast";

import { Badge, Button, Card, Table, TBody, TD, TH, THead, TR } from "@/components/ui";
import { useReconfigureSpace, useUnits } from "@/hooks/useUnits";
import { getErrorMessage } from "@/lib/apiError";
import { cn } from "@/lib/cn";
import { formatKES } from "@/lib/money";
import type { SpaceUnit, TenantDetail } from "@/lib/types";

import { Field, inputCls } from "./shared";

const KES = formatKES;

export function SpacePanel({ tenant, canManage }: { tenant: TenantDetail; canManage: boolean }) {
  const space = useMemo(() => tenant.space_units ?? [], [tenant.space_units]);
  const head = space[0];
  const [editing, setEditing] = useState(false);
  const [adding, setAdding] = useState<number[]>([]);
  const [removing, setRemoving] = useState<number[]>([]);
  const [rent, setRent] = useState("");
  const [rentTouched, setRentTouched] = useState(false);
  const reconfigure = useReconfigureSpace(head?.id ?? 0);

  // Units that can join: vacant commercial units in the same property that are
  // not already in a space of their own. The server re-checks every rule.
  const { data: vacant } = useUnits(
    { building: tenant.building_id, status: "vacant" },
  );
  const candidates = useMemo(
    () => (vacant ?? []).filter(
      (u) => u.classification === "BUSINESS" && u.combined_into == null
        && (u.combined_units ?? []).length === 0 && u.id !== head?.id,
    ),
    [vacant, head?.id],
  );

  const suggested = useMemo(() => {
    const byId = new Map<number, { monthly_rent: string }>(
      [...space, ...candidates].map((u) => [u.id, u]),
    );
    const delta = (ids: number[]) => ids.reduce((s, id) => s + Number(byId.get(id)?.monthly_rent ?? 0), 0);
    return Math.max(Number(tenant.monthly_rent) + delta(adding) - delta(removing), 0);
  }, [space, candidates, adding, removing, tenant.monthly_rent]);

  useEffect(() => {
    if (!rentTouched) setRent(String(suggested));
  }, [suggested, rentTouched]);

  if (!head || tenant.unit_classification !== "BUSINESS") return null;
  if (space.length < 2 && !canManage) return null;

  function reset() {
    setEditing(false); setAdding([]); setRemoving([]); setRentTouched(false);
  }

  function toggle(list: number[], set: (v: number[]) => void, id: number) {
    set(list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);
  }

  async function save() {
    try {
      await reconfigure.mutateAsync({ add: adding, remove: removing, monthly_rent: rent });
      toast.success("Space updated — the new rent bills from the next run");
      reset();
    } catch (e) {
      toast.error(getErrorMessage(e, "Could not change the space."));
    }
  }

  const changed = adding.length > 0 || removing.length > 0;
  const rentRow = (u: SpaceUnit, isHead: boolean) => (
    <TR key={u.id} className={cn(removing.includes(u.id) && "opacity-50 line-through")}>
      <TD className="font-medium text-content">
        {u.label}
        {isHead && space.length > 1 && <Badge tone="neutral" className="ml-2">Head</Badge>}
      </TD>
      <TD className="text-right tabular-nums">{KES(u.monthly_rent)}</TD>
      {editing && (
        <TD className="text-right">
          {!isHead && (
            <Button type="button" size="sm" variant="ghost" onClick={() => toggle(removing, setRemoving, u.id)}>
              <Minus className="h-3.5 w-3.5" /> {removing.includes(u.id) ? "Keep" : "Remove"}
            </Button>
          )}
        </TD>
      )}
    </TR>
  );

  return (
    <Card padding="none">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-hairline px-5 py-4">
        <div>
          <h2 className="flex items-center gap-2 font-semibold text-content">
            <Layers className="h-4 w-4" /> Space · {tenant.space_label ?? head.label}
          </h2>
          <p className="text-xs text-content-muted">
            {space.length} unit{space.length === 1 ? "" : "s"} · billed{" "}
            {KES(tenant.monthly_rent)} + VAT a month
          </p>
        </div>
        {canManage && tenant.status !== "moved_out" && tenant.status !== "archived" && !editing && (
          <Button type="button" size="sm" variant="outline" onClick={() => setEditing(true)}>
            <Plus className="h-4 w-4" /> Add or remove units
          </Button>
        )}
      </div>

      <Table minWidth={420}>
        <THead>
          <TR>
            <TH>Unit</TH><TH className="text-right">Standing rent</TH>
            {editing && <TH />}
          </TR>
        </THead>
        <TBody>{space.map((u, i) => rentRow(u, i === 0))}</TBody>
      </Table>

      {editing && (
        <div className="space-y-4 border-t border-hairline px-5 py-4">
          <div>
            <p className="mb-2 text-sm font-medium text-content">Add vacant commercial units in this property</p>
            {candidates.length === 0 ? (
              <p className="text-sm text-content-muted">No vacant commercial units in this property.</p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {candidates.map((u) => (
                  <label
                    key={u.id}
                    className={cn(
                      "flex cursor-pointer items-center gap-2 rounded-md border px-3 py-1.5 text-sm",
                      adding.includes(u.id) ? "border-teal-600 bg-teal-600/10" : "border-border",
                    )}
                  >
                    <input type="checkbox" checked={adding.includes(u.id)} onChange={() => toggle(adding, setAdding, u.id)} />
                    {u.label} <span className="text-content-muted">{KES(u.monthly_rent)}</span>
                  </label>
                ))}
              </div>
            )}
          </div>
          <div className="grid gap-3 sm:max-w-xs">
            <Field label="Rent for the space (excl. VAT)">
              <input
                type="number" min={0} step="0.01" value={rent} className={inputCls}
                onChange={(e) => { setRent(e.target.value); setRentTouched(true); }}
              />
            </Field>
          </div>
          <p className="-mt-2 text-[11px] text-content-muted">
            Suggested {KES(suggested)}: the current rent moved by each unit&rsquo;s standing rent. Change it if a
            different figure was agreed. Billed from the next run; months already charged are not restated.
          </p>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={reset}>Cancel</Button>
            <Button type="button" onClick={save} disabled={!changed || rent === ""} loading={reconfigure.isPending}>
              Save space
            </Button>
          </div>
        </div>
      )}
    </Card>
  );
}
