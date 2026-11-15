import {
  BarChart3,
  Bell,
  Building,
  Building2,
  Calculator,
  CreditCard,
  DoorOpen,
  Droplets,
  FileText,
  History,
  Home,
  Landmark,
  LayoutDashboard,
  LineChart,
  MessagesSquare,
  Receipt,
  Scale,
  Settings,
  ShieldCheck,
  Sprout,
  UserCog,
  Users,
  Wallet,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { CAP, type Capability, subRouteRequirement } from "@/lib/access";

export type ViewKey =
  | "dashboard"
  | "buildings"
  | "units"
  | "tenants"
  | "payments"
  | "reconciliation"
  | "expenses"
  | "income"
  | "water"
  | "accounting"
  | "notifications"
  | "reports"
  | "activity"
  | "users"
  | "settings";

export interface NavItem {
  key: ViewKey;
  to: string;
  label: string;
  icon: LucideIcon;
  togglable: boolean;
  /** What the person needs to see this page (lib/access.ts). None: everyone. */
  requires?: Capability;
  description?: string;
}

const F = CAP.VIEW_FINANCE;
const P = CAP.VIEW_PROPERTY;

export const NAV_ITEMS: NavItem[] = [
  { key: "dashboard", to: "/dashboard", label: "Dashboard", icon: LayoutDashboard, togglable: false, requires: F },
  { key: "buildings", to: "/buildings", label: "Properties", icon: Building2, togglable: true, requires: P, description: "Manage your properties and bank details" },
  { key: "units", to: "/units", label: "Units", icon: Home, togglable: true, requires: P, description: "Track unit availability and rent" },
  { key: "tenants", to: "/tenants", label: "Tenants", icon: Users, togglable: true, requires: P, description: "Tenant directory and KYC" },
  { key: "payments", to: "/payments", label: "Payments", icon: CreditCard, togglable: true, requires: F, description: "Rent collection, M-Pesa, receipts" },
  { key: "reconciliation", to: "/reconciliation", label: "Reconciliation", icon: Scale, togglable: true, requires: F, description: "Assign unmatched bank credits to tenants" },
  { key: "expenses", to: "/expenses", label: "Expenses", icon: Receipt, togglable: true, requires: F, description: "Operating costs and disbursements" },
  { key: "income", to: "/income", label: "Other Income", icon: Sprout, togglable: true, requires: F, description: "Manual income (farm produce, non-tenant)" },
  { key: "water", to: "/water", label: "Water Management", icon: Droplets, togglable: true, requires: P, description: "Meter readings and water billing" },
  { key: "accounting", to: "/accounting", label: "Accounting", icon: Calculator, togglable: true, requires: F, description: "Chart of accounts, P&L, balance sheet" },
  { key: "notifications", to: "/notifications", label: "Notifications", icon: Bell, togglable: true, requires: F, description: "Reminders and alerts" },
  { key: "reports", to: "/reports", label: "Reports", icon: BarChart3, togglable: true, requires: F, description: "Statements and analytics" },
  { key: "activity", to: "/activity", label: "Activity Log", icon: History, togglable: false, requires: CAP.VIEW_ACTIVITY },
  { key: "users", to: "/users", label: "Users", icon: UserCog, togglable: false, requires: CAP.MANAGE_USERS },
  { key: "settings", to: "/settings", label: "Settings", icon: Settings, togglable: false },
];

/** What a URL needs: a money screen hanging off a tenant, else its menu page's own. */
export function pageRequirement(pathname: string): Capability | undefined {
  const sub = subRouteRequirement(pathname);
  if (sub) return sub;
  const item = NAV_ITEMS.find((i) => pathname === i.to || pathname.startsWith(`${i.to}/`));
  return item?.requires;
}

/** Where someone lands: the first page in the menu they may see (the dashboard for most). */
export function homePath(allowed: (cap: Capability) => boolean): string {
  return NAV_ITEMS.find((i) => !i.requires || allowed(i.requires))?.to ?? "/settings";
}

/**
 * The menu, as one tree read by the desktop sidebar, the icon rail's flyouts
 * and the phone drawer.
 *
 * - `link`  — opens a page, or a tab inside one (Accounting and Reports keep
 *   their views as `?acct=` / `?tab=` tabs). Visibility comes from the page's
 *   NAV_ITEMS entry: owner-only pages and pages hidden in Settings drop out.
 * - `group` — a collapsible parent. It is not a page; it opens and closes.
 * - `label` — a heading inside a group (Accounting's Financial Statements and
 *   Books & Controls), not clickable.
 *
 * Groups and labels left with nothing visible disappear.
 */
export interface NavTab {
  param: string;
  /** The tab the link opens. */
  value: string;
  /**
   * Every tab the link stands for, so it stays highlighted on all of them
   * (a Reports category covers several tabs). Defaults to `[value]`.
   */
  covers?: string[];
}

export type NavNode =
  | { kind: "link"; id: string; page: ViewKey; label?: string; icon?: LucideIcon; tab?: NavTab }
  | { kind: "group"; id: string; label: string; icon: LucideIcon; children: NavNode[] }
  | { kind: "label"; id: string; label: string; children: NavNode[] };

/** The tab a page shows when its URL names none. Must be the page's first tab (nav.test.ts). */
export const DEFAULT_TAB: Partial<Record<ViewKey, NavTab>> = {
  accounting: { param: "acct", value: "balance_sheet" },
  reports: { param: "tab", value: "monthly" },
};

const page = (key: ViewKey, extra: Partial<Extract<NavNode, { kind: "link" }>> = {}): NavNode => ({
  kind: "link", id: key, page: key, ...extra,
});
const acct = (value: string, label: string): NavNode => ({
  kind: "link", id: `accounting-${value}`, page: "accounting", label, tab: { param: "acct", value },
});
const report = (id: string, label: string, icon: LucideIcon, covers: string[]): NavNode => ({
  kind: "link", id: `reports-${id}`, page: "reports", label, icon, tab: { param: "tab", value: covers[0], covers },
});

export const NAV_TREE: NavNode[] = [
  page("dashboard"),
  {
    kind: "group", id: "property", label: "Property Management", icon: Building2,
    children: [page("buildings", { icon: Building }), page("units"), page("tenants"), page("water")],
  },
  {
    kind: "group", id: "finance", label: "Finance", icon: Landmark,
    children: [
      page("payments"),
      page("reconciliation"),
      page("income"),
      page("expenses"),
      {
        kind: "group", id: "accounting", label: "Accounting", icon: Calculator,
        children: [
          {
            kind: "label", id: "accounting-statements", label: "Financial Statements",
            children: [acct("balance_sheet", "Balance Sheet"), acct("pnl", "Profit & Loss"), acct("trial_balance", "Trial Balance")],
          },
          {
            kind: "label", id: "accounting-books", label: "Books & Controls",
            children: [
              acct("ledger", "General Ledger"),
              acct("coa", "Chart of Accounts"),
              acct("petty_cash", "Petty Cash"),
              acct("budgeting", "Budget vs Actual"),
            ],
          },
        ],
      },
    ],
  },
  {
    kind: "group", id: "communications", label: "Communications", icon: MessagesSquare,
    children: [page("notifications")],
  },
  {
    kind: "group", id: "reports", label: "Reports", icon: BarChart3,
    children: [
      report("collections", "Collections & Arrears", Wallet,
        ["monthly", "annual", "arrears", "rent_balances", "overpayments", "aging"]),
      report("occupancy", "Occupancy", DoorOpen, ["occupancy", "vacant", "expiring", "moves"]),
      report("statements", "Tenant Statements", FileText, ["tenant_stmt", "unit_stmt", "landlord", "tenant"]),
      report("financials", "Financial Reports", LineChart, ["pnl", "trial", "breakdown"]),
    ],
  },
  {
    kind: "group", id: "admin", label: "Administration", icon: ShieldCheck,
    children: [page("users"), page("activity"), page("settings")],
  },
];

export const navItem = (key: ViewKey): NavItem => NAV_ITEMS.find((i) => i.key === key)!;

/** Where a link goes. */
export function linkHref(node: Extract<NavNode, { kind: "link" }>): string {
  const { to } = navItem(node.page);
  return node.tab ? `${to}?${node.tab.param}=${node.tab.value}` : to;
}

/**
 * Whether a link is the page on screen, read from the URL alone. A page-level
 * link also covers the page's own sub-routes (/buildings/12/edit). A tab link
 * matches its tabs; a page with no tab in its URL shows its default tab.
 */
export function isLinkActive(
  node: Extract<NavNode, { kind: "link" }>,
  pathname: string,
  search: string
): boolean {
  const { to } = navItem(node.page);
  if (!node.tab) return pathname === to || pathname.startsWith(`${to}/`);
  if (pathname !== to) return false;
  const current = new URLSearchParams(search).get(node.tab.param) ?? DEFAULT_TAB[node.page]?.value;
  return (node.tab.covers ?? [node.tab.value]).includes(current ?? "");
}

/** Every link in a (sub)tree, depth first. */
export function links(nodes: NavNode[]): Extract<NavNode, { kind: "link" }>[] {
  return nodes.flatMap((n) => (n.kind === "link" ? [n] : links(n.children)));
}

/** The ids of every group above the active link, outermost first, then the link's. */
export function activePath(nodes: NavNode[], pathname: string, search: string): string[] {
  for (const n of nodes) {
    if (n.kind === "link") {
      if (isLinkActive(n, pathname, search)) return [n.id];
    } else {
      const below = activePath(n.children, pathname, search);
      // Headings are not sections that open or close, so they are not on the path.
      if (below.length) return n.kind === "group" ? [n.id, ...below] : below;
    }
  }
  return [];
}
