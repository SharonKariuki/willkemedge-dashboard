import {
  BarChart3,
  Bell,
  Building2,
  Calculator,
  CreditCard,
  Home,
  LayoutDashboard,
  Receipt,
  Scale,
  Droplets,
  History,
  Settings,
  Sprout,
  Users,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

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
  | "settings";

export interface NavItem {
  key: ViewKey;
  to: string;
  label: string;
  icon: LucideIcon;
  togglable: boolean;
  /** Shown only to the owner/director (`can_forgive_money`). */
  ownerOnly?: boolean;
  description?: string;
}

export const NAV_ITEMS: NavItem[] = [
  { key: "dashboard", to: "/dashboard", label: "Dashboard", icon: LayoutDashboard, togglable: false },
  { key: "buildings", to: "/buildings", label: "Buildings", icon: Building2, togglable: true, description: "Manage your properties and bank details" },
  { key: "units", to: "/units", label: "Units", icon: Home, togglable: true, description: "Track unit availability and rent" },
  { key: "tenants", to: "/tenants", label: "Tenants", icon: Users, togglable: true, description: "Tenant directory and KYC" },
  { key: "payments", to: "/payments", label: "Payments", icon: CreditCard, togglable: true, description: "Rent collection, M-Pesa, receipts" },
  { key: "reconciliation", to: "/reconciliation", label: "Reconciliation", icon: Scale, togglable: true, description: "Assign unmatched bank credits to tenants" },
  { key: "expenses", to: "/expenses", label: "Expenses", icon: Receipt, togglable: true, description: "Operating costs and disbursements" },
  { key: "income", to: "/income", label: "Income", icon: Sprout, togglable: true, description: "Manual income (farm produce, non-tenant)" },
  { key: "water", to: "/water", label: "Water", icon: Droplets, togglable: true, description: "Meter readings and water billing" },
  { key: "accounting", to: "/accounting", label: "Accounting", icon: Calculator, togglable: true, description: "Chart of accounts, P&L, balance sheet" },
  { key: "notifications", to: "/notifications", label: "Notifications", icon: Bell, togglable: true, description: "Reminders and alerts" },
  { key: "reports", to: "/reports", label: "Reports", icon: BarChart3, togglable: true, description: "Statements and analytics" },
  { key: "activity", to: "/activity", label: "Activity", icon: History, togglable: false, ownerOnly: true },
  { key: "settings", to: "/settings", label: "Settings", icon: Settings, togglable: false },
];

/**
 * A view inside a page, reached by a query parameter: the Accounting and
 * Reports pages keep their sub-views as tabs. `value` must be one of the
 * page's own tab keys (nav.test.ts checks this).
 */
export interface NavChild {
  label: string;
  param: string;
  value: string;
}

export interface NavChildGroup {
  /** Sub-heading shown above the group; omitted for a single flat list. */
  label?: string;
  items: NavChild[];
}

const acct = (value: string, label: string): NavChild => ({ label, param: "acct", value });
const report = (value: string, label: string): NavChild => ({ label, param: "tab", value });

/** Pages that open into their own sub-views in the menu. */
export const NAV_CHILDREN: Partial<Record<ViewKey, NavChildGroup[]>> = {
  accounting: [
    {
      items: [
        acct("balance_sheet", "Balance Sheet"),
        acct("pnl", "Profit & Loss"),
        acct("trial_balance", "Trial Balance"),
        acct("ledger", "General Ledger"),
        acct("coa", "Chart of Accounts"),
        acct("petty_cash", "Petty Cash"),
        acct("budgeting", "Budget vs Actual"),
      ],
    },
  ],
  reports: [
    { label: "Collections", items: [report("monthly", "Collections"), report("annual", "Annual Income")] },
    {
      label: "Balances",
      items: [
        report("arrears", "Arrears"),
        report("rent_balances", "Rent Balances"),
        report("overpayments", "Overpayments"),
        report("aging", "Aging Balances"),
      ],
    },
    {
      label: "Statements",
      items: [
        report("tenant_stmt", "Tenant Statement"),
        report("unit_stmt", "Unit Statement"),
        report("landlord", "Landlord Statement"),
        report("tenant", "Tenant History"),
      ],
    },
    {
      label: "Occupancy",
      items: [
        report("occupancy", "Occupancy"),
        report("vacant", "Vacant Units"),
        report("expiring", "Expiring Leases"),
        report("moves", "Move Log"),
      ],
    },
    {
      label: "Financials",
      items: [report("pnl", "P&L"), report("trial", "Trial Balance"), report("breakdown", "Expense Breakdown")],
    },
  ],
};

export interface NavSection {
  /** Heading above the section; the first section (Dashboard) has none. */
  label?: string;
  keys: ViewKey[];
}

/** The menu, top to bottom. Every page in NAV_ITEMS appears exactly once here or in NAV_FOOTER. */
export const NAV_SECTIONS: NavSection[] = [
  { keys: ["dashboard"] },
  { label: "Property", keys: ["buildings", "units", "tenants"] },
  { label: "Money in", keys: ["payments", "reconciliation", "water", "income"] },
  { label: "Money out", keys: ["expenses"] },
  { label: "Books", keys: ["accounting", "reports"] },
  { label: "Messaging", keys: ["notifications"] },
];

/** Pinned below the scrolling menu, beside the profile. */
export const NAV_FOOTER: ViewKey[] = ["activity", "settings"];

export const navItem = (key: ViewKey): NavItem => NAV_ITEMS.find((i) => i.key === key)!;

export const childHref = (parent: NavItem, child: NavChild) => `${parent.to}?${child.param}=${child.value}`;

/**
 * Whether a child is the view on screen. A page with no tab in its URL shows
 * its first tab, so that child counts as active too.
 */
export function isChildActive(
  parent: NavItem,
  child: NavChild,
  pathname: string,
  search: string
): boolean {
  if (pathname !== parent.to) return false;
  const current = new URLSearchParams(search).get(child.param);
  if (current) return current === child.value;
  const first = NAV_CHILDREN[parent.key]?.[0]?.items[0];
  return first?.value === child.value;
}

export const isUnder = (item: NavItem, pathname: string) =>
  pathname === item.to || pathname.startsWith(`${item.to}/`);
