/**
 * Caretakers on a property's page: who looks after it, and a way to add or
 * take one off without going round by the Users page. The same rule as
 * there applies - a caretaker always looks after at least one property.
 */
import { MailPlus, UserMinus, UserPlus, Wrench } from "lucide-react";
import { useState } from "react";
import toast from "react-hot-toast";
import { Link } from "react-router-dom";

import { Button, Card } from "@/components/ui";
import { type ManagedUser, useUpdateUser, useUsers } from "@/hooks/useUsers";
import { getErrorMessage } from "@/lib/apiError";

const nameOf = (u: ManagedUser) => u.full_name || u.email;

export function BuildingCaretakers({ buildingId, buildingName }: { buildingId: number; buildingName: string }) {
  const { data, isLoading } = useUsers();
  const update = useUpdateUser();
  const [picked, setPicked] = useState("");

  const caretakers = (data?.users ?? []).filter((u) => u.role === "caretaker" && u.status !== "deactivated");
  const here = caretakers.filter((u) => u.buildings.some((b) => b.id === buildingId));
  const others = caretakers.filter((u) => !u.buildings.some((b) => b.id === buildingId));

  const setBuildings = async (u: ManagedUser, ids: number[], done: string) => {
    try {
      await update.mutateAsync({ id: u.id, buildings: ids });
      toast.success(done);
    } catch (err) {
      toast.error(getErrorMessage(err, "Couldn't change the caretaker's properties"));
    }
  };

  const add = async () => {
    const u = others.find((c) => String(c.id) === picked);
    if (!u) return;
    await setBuildings(u, [...u.buildings.map((b) => b.id), buildingId], `${nameOf(u)} now looks after ${buildingName}`);
    setPicked("");
  };

  const remove = async (u: ManagedUser) => {
    if (u.buildings.length <= 1) {
      toast.error(
        `${nameOf(u)} only looks after ${buildingName}. Give them another property first, or switch their account off on the Users page.`,
      );
      return;
    }
    await setBuildings(
      u,
      u.buildings.map((b) => b.id).filter((id) => id !== buildingId),
      `${nameOf(u)} no longer looks after ${buildingName}`,
    );
  };

  return (
    <Card padding="md">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Wrench className="h-4 w-4 text-teal-600" />
          <h2 className="font-semibold text-content">Caretakers</h2>
        </div>
        <Link to="/users?invite=1" className="inline-flex items-center gap-1 text-xs font-medium text-teal-700 hover:underline">
          <MailPlus className="h-3.5 w-3.5" /> Invite a new caretaker
        </Link>
      </div>

      {isLoading ? (
        <p className="text-sm text-content-muted">Loading…</p>
      ) : here.length === 0 ? (
        <p className="text-sm text-content-muted">No caretaker looks after this property yet.</p>
      ) : (
        <ul className="divide-y divide-hairline">
          {here.map((u) => (
            <li key={u.id} className="flex items-center justify-between gap-3 py-2">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-content">{nameOf(u)}</p>
                <p className="truncate text-xs text-content-muted">
                  {u.status === "invited" ? "Invited - hasn't signed in yet" : u.email}
                  {u.buildings.length > 1 && ` · also ${u.buildings.filter((b) => b.id !== buildingId).map((b) => b.name).join(", ")}`}
                </p>
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => void remove(u)}
                disabled={update.isPending}
                aria-label={`Take ${nameOf(u)} off ${buildingName}`}
              >
                <UserMinus className="h-3.5 w-3.5" /> Remove
              </Button>
            </li>
          ))}
        </ul>
      )}

      {others.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-hairline pt-3">
          <label htmlFor={`caretaker-add-${buildingId}`} className="sr-only">Add a caretaker to {buildingName}</label>
          <select
            id={`caretaker-add-${buildingId}`}
            value={picked}
            onChange={(e) => setPicked(e.target.value)}
            className="min-w-[200px] flex-1 rounded-md border border-border bg-surface px-3 py-1.5 text-sm text-content focus:outline-none focus:ring-2 focus:ring-ring/25"
          >
            <option value="">Add an existing caretaker…</option>
            {others.map((u) => (
              <option key={u.id} value={u.id}>{nameOf(u)}</option>
            ))}
          </select>
          <Button size="sm" onClick={() => void add()} disabled={!picked || update.isPending}>
            <UserPlus className="h-3.5 w-3.5" /> Add
          </Button>
        </div>
      )}
    </Card>
  );
}
