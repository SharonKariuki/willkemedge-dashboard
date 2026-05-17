import {
  BarChart3,
  Bell,
  Building2,
  CreditCard,
  Home,
  LayoutDashboard,
  Receipt,
  Settings,
  Users,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

export type ViewKey =
  | "dashboard"
  | "buildings"
  | "units"
  | "tenants"
  | "payments"
  | "expenses"
  | "notifications"
  | "reports"
  | "settings";

export interface NavItem {
  key: ViewKey;
  to: string;
  label: string;
  icon: LucideIcon;
  togglable: boolean;
  description?: string;
}

export const NAV_ITEMS: NavItem[] = [
  { key: "dashboard", to: "/dashboard", label: "Dashboard", icon: LayoutDashboard, togglable: false },
  { key: "buildings", to: "/buildings", label: "Buildings", icon: Building2, togglable: true, description: "Manage your properties and bank details" },
  { key: "units", to: "/units", label: "Units", icon: Home, togglable: true, description: "Track unit availability and rent" },
  { key: "tenants", to: "/tenants", label: "Tenants", icon: Users, togglable: true, description: "Tenant directory and KYC" },
  { key: "payments", to: "/payments", label: "Payments", icon: CreditCard, togglable: true, description: "Rent collection, M-Pesa, receipts" },
  { key: "expenses", to: "/expenses", label: "Expenses", icon: Receipt, togglable: true, description: "Operating costs and disbursements" },
  { key: "notifications", to: "/notifications", label: "Notifications", icon: Bell, togglable: true, description: "Reminders and alerts" },
  { key: "reports", to: "/reports", label: "Reports", icon: BarChart3, togglable: true, description: "Statements and analytics" },
  { key: "settings", to: "/settings", label: "Settings", icon: Settings, togglable: false },
];
