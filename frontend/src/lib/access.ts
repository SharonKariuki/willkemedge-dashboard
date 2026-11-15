/**
 * What the signed-in person may do, as the API told us (`/auth/me/` →
 * `capabilities`). Mirrors backend/apps/accounts/access.py.
 *
 * This only decides what is worth showing - menus, pages, buttons. The API
 * enforces the same rules on every request whatever the browser shows.
 */
import type { StoredUser } from "@/lib/authStorage";

export const CAP = {
  VIEW_FINANCE: "view_finance",
  RECORD_MONEY: "record_money",
  FORGIVE_MONEY: "forgive_money",
  VIEW_PROPERTY: "view_property",
  MANAGE_PROPERTY: "manage_property",
  RECORD_WATER: "record_water",
  LOG_MAINTENANCE: "log_maintenance",
  SEND_MESSAGES: "send_messages",
  VIEW_ACTIVITY: "view_activity",
  MANAGE_USERS: "manage_users",
} as const;

export type Capability = (typeof CAP)[keyof typeof CAP];

/**
 * A session saved before capabilities existed has only the old money flags;
 * read them until `/auth/me/` refreshes it, rather than locking anyone out.
 */
function legacy(user: StoredUser): Capability[] {
  if (user.can_forgive_money) return Object.values(CAP);
  const base: Capability[] = [CAP.VIEW_FINANCE, CAP.VIEW_PROPERTY];
  return user.can_record_money
    ? [...base, CAP.RECORD_MONEY, CAP.MANAGE_PROPERTY, CAP.RECORD_WATER, CAP.LOG_MAINTENANCE, CAP.SEND_MESSAGES]
    : base;
}

export function capabilitiesOf(user: StoredUser | null | undefined): Capability[] {
  if (!user) return [];
  return (user.capabilities as Capability[] | undefined) ?? legacy(user);
}

export function can(user: StoredUser | null | undefined, cap: Capability): boolean {
  return capabilitiesOf(user).includes(cap);
}

/**
 * Pages that need more than their menu entry says - the money screens that
 * hang off a tenant. Checked before the menu's own requirement.
 */
const SUB_ROUTES: [RegExp, Capability][] = [
  [/^\/tenants\/[^/]+\/(charges|credits|deposit)\b/, CAP.FORGIVE_MONEY],
  [/^\/buildings\/(new|[^/]+\/edit)\b/, CAP.MANAGE_PROPERTY],
];

export function subRouteRequirement(pathname: string): Capability | undefined {
  return SUB_ROUTES.find(([re]) => re.test(pathname))?.[1];
}
