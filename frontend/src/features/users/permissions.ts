/**
 * A person's permissions: their role's, with their own changes on top.
 * Mirrors backend/apps/accounts/access.py `effective` so the checklist shows
 * exactly what the API will store. The API checks again regardless.
 */
import type { PermissionOption } from "@/hooks/useUsers";

export interface PermissionCatalog {
  permissions: PermissionOption[];
  roleCapabilities: Record<string, string[]>;
  scopedRoles: string[];
}

export interface Changes {
  added: string[];
  removed: string[];
}

export const NO_CHANGES: Changes = { added: [], removed: [] };

const baseOf = (catalog: PermissionCatalog, role: string) => new Set(catalog.roleCapabilities[role] ?? []);

/** What someone with this role and these changes can do. */
export function effective(catalog: PermissionCatalog, role: string, changes: Changes): Set<string> {
  const scoped = catalog.scopedRoles.includes(role);
  const caps = new Set([...baseOf(catalog, role), ...(scoped ? [] : changes.added)]);
  changes.removed.forEach((c) => caps.delete(c));
  // Anything whose requirement is gone goes too.
  let changed = true;
  while (changed) {
    changed = false;
    for (const p of catalog.permissions) {
      if (caps.has(p.value) && !p.requires.every((r) => caps.has(r))) {
        caps.delete(p.value);
        changed = true;
      }
    }
  }
  return caps;
}

/** The changes that turn the role into `final`. */
function changesFor(catalog: PermissionCatalog, role: string, final: Set<string>): Changes {
  const base = baseOf(catalog, role);
  const order = catalog.permissions.map((p) => p.value);
  return {
    added: order.filter((c) => final.has(c) && !base.has(c)),
    removed: order.filter((c) => base.has(c) && !final.has(c)),
  };
}

/** Tick or untick one permission. Ticking brings what it needs along;
 *  unticking takes what depends on it away. */
export function toggle(
  catalog: PermissionCatalog, role: string, changes: Changes, cap: string, on: boolean,
): Changes {
  const final = effective(catalog, role, changes);
  const byValue = new Map(catalog.permissions.map((p) => [p.value, p]));
  if (on) {
    final.add(cap);
    byValue.get(cap)?.requires.forEach((r) => final.add(r));
  } else {
    final.delete(cap);
    catalog.permissions.filter((p) => p.requires.includes(cap)).forEach((p) => final.delete(p.value));
  }
  return changesFor(catalog, role, final);
}

/**
 * Whether this box may be ticked by the signed-in person. Anything the role
 * already has can always be turned back on; beyond that, a building-limited
 * role gains nothing, and the rest needs the grant (or for them to hold it
 * already, so an owner editing someone doesn't undo the superadmin's grant).
 */
export function canTurnOn(
  catalog: PermissionCatalog, role: string, cap: string, heldBefore: string[],
): boolean {
  const base = baseOf(catalog, role);
  if (base.has(cap)) return true;
  if (catalog.scopedRoles.includes(role)) return false;
  const option = catalog.permissions.find((p) => p.value === cap);
  if (!option) return false;
  const needs = [cap, ...option.requires.filter((r) => !base.has(r))];
  return needs.every((c) => heldBefore.includes(c) || catalog.permissions.find((p) => p.value === c)?.grantable);
}
