/**
 * The permissions behind a role, with this person's own changes on top.
 * Ticked = they can do it. A change from the role is marked, and can be
 * put back with one click.
 */
import { cn } from "@/lib/cn";

import { type Changes, NO_CHANGES, type PermissionCatalog, canTurnOn, effective, toggle } from "./permissions";

export function PermissionChecklist({
  idPrefix,
  catalog,
  role,
  changes,
  heldBefore,
  onChange,
}: {
  idPrefix: string;
  catalog: PermissionCatalog;
  role: string;
  changes: Changes;
  /** Extra permissions the person holds today (kept even if the editor couldn't give them). */
  heldBefore: string[];
  onChange: (c: Changes) => void;
}) {
  const base = new Set(catalog.roleCapabilities[role] ?? []);
  const final = effective(catalog, role, changes);
  const scoped = catalog.scopedRoles.includes(role);
  const areas = [...new Set(catalog.permissions.map((p) => p.area))];
  const changed = changes.added.length + changes.removed.length > 0;

  return (
    <fieldset>
      <div className="mb-1 flex items-baseline justify-between gap-2">
        <legend className="text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">What they can do</legend>
        {changed && (
          <button
            type="button"
            onClick={() => onChange(NO_CHANGES)}
            className="text-xs font-medium text-teal-700 hover:underline"
          >
            Back to the role's defaults
          </button>
        )}
      </div>
      <p className="mb-2 text-xs text-ink-500">
        {scoped
          ? "A caretaker only sees their own buildings, so you can take permissions away but not add any."
          : "Ticked boxes come from the role. Change any of them for this person only."}
      </p>
      <div className="max-h-72 space-y-3 overflow-y-auto rounded-md hairline p-2.5">
        {areas.map((area) => (
          <div key={area}>
            <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-ink-400">{area}</p>
            {catalog.permissions
              .filter((p) => p.area === area)
              .map((p) => {
                const on = final.has(p.value);
                const id = `${idPrefix}-perm-${p.value}`;
                const locked = !on && !canTurnOn(catalog, role, p.value, heldBefore);
                const mark = on && !base.has(p.value) ? "added" : !on && base.has(p.value) ? "removed" : null;
                return (
                  <div key={p.value} className="flex items-start gap-2 rounded px-1.5 py-1 hover:bg-surface-raised">
                    <input
                      id={id}
                      type="checkbox"
                      checked={on}
                      disabled={locked}
                      onChange={(e) => onChange(toggle(catalog, role, changes, p.value, e.target.checked))}
                      aria-describedby={`${id}-hint`}
                      className="mt-0.5 h-4 w-4 accent-sage-600 disabled:opacity-40"
                    />
                    <div className="min-w-0 flex-1">
                      <label htmlFor={id} className={cn("text-sm", locked ? "text-ink-400" : "text-ink-900")}>
                        {p.label}
                      </label>
                      {mark && (
                        <span
                          className={cn(
                            "ml-2 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
                            mark === "added" ? "bg-sage-500/15 text-sage-700" : "bg-orange-500/15 text-orange-700",
                          )}
                        >
                          {mark}
                        </span>
                      )}
                      <p id={`${id}-hint`} className="text-xs text-ink-500">
                        {p.hint}
                        {locked && !scoped && !p.grantable ? " Only the superadmin can give this." : ""}
                      </p>
                    </div>
                  </div>
                );
              })}
          </div>
        ))}
      </div>
    </fieldset>
  );
}
