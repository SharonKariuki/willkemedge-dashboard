import {
  BarChart3,
  Bell,
  Building2,
  ChevronLeft,
  ChevronRight,
  CreditCard,
  Home,
  LayoutDashboard,
  Receipt,
  Settings,
  Users,
} from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";

import { cn } from "@/lib/cn";

const NAV_ITEMS = [
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "/buildings", label: "Buildings", icon: Building2 },
  { to: "/units", label: "Units", icon: Home },
  { to: "/tenants", label: "Tenants", icon: Users },
  { to: "/payments", label: "Payments", icon: CreditCard },
  { to: "/expenses", label: "Expenses", icon: Receipt },
  { to: "/notifications", label: "Notifications", icon: Bell },
  { to: "/reports", label: "Reports", icon: BarChart3 },
  { to: "/settings", label: "Settings", icon: Settings },
];

const STORAGE_KEY = "willkemedge-sidebar-collapsed";

export default function Sidebar() {
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) === "1";
    } catch {
      return false;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, collapsed ? "1" : "0");
    } catch {
      // ignore
    }
  }, [collapsed]);

  const toggle = () => setCollapsed((c) => !c);

  return (
    <aside
      className={cn(
        "hidden shrink-0 transition-[width] duration-300 ease-out lg:sticky lg:top-4 lg:flex lg:h-[calc(100vh-2rem)] lg:flex-col lg:py-4 lg:pl-4",
        collapsed ? "lg:w-[88px]" : "lg:w-64"
      )}
    >
      <div className="sidebar-shell relative flex h-full flex-col rounded-xl p-3">
        {/* Collapse toggle — floats on the right edge */}
        <button
          type="button"
          onClick={toggle}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className="absolute -right-3 top-7 z-10 flex h-7 w-7 items-center justify-center rounded-full bg-ochre-500 text-ink-900 shadow-float ring-2 ring-[#1F1512] transition-all hover:scale-110 hover:bg-ochre-400"
        >
          {collapsed ? (
            <ChevronRight className="h-3.5 w-3.5" />
          ) : (
            <ChevronLeft className="h-3.5 w-3.5" />
          )}
        </button>

        {/* Brand */}
        <div
          className={cn(
            "flex items-center gap-3 pb-6 pt-2",
            collapsed ? "justify-center" : "px-2"
          )}
        >
          <div className="relative flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-ochre-500 text-ink-900 shadow-glass ring-1 ring-ochre-600/40">
            <span className="font-display text-lg font-semibold leading-none">W</span>
          </div>
          {!collapsed && (
            <div className="min-w-0 animate-fade-up">
              <p className="font-display text-base font-semibold leading-tight text-white">
                Willkemedge
              </p>
              <p className="truncate text-[11px] uppercase tracking-[0.14em] text-ochre-400/80">
                Property Suite
              </p>
            </div>
          )}
        </div>

        {/* Primary nav */}
        <nav className="flex flex-1 flex-col gap-1">
          {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              title={collapsed ? label : undefined}
              className={({ isActive }) =>
                cn(
                  "group relative flex items-center gap-3 rounded-md py-2.5 text-sm font-medium transition-all",
                  collapsed ? "justify-center px-2" : "px-3",
                  isActive
                    ? "bg-ochre-500/12 text-white"
                    : "text-white/65 hover:bg-white/5 hover:text-white"
                )
              }
            >
              {({ isActive }) => (
                <>
                  {isActive && (
                    <span
                      className={cn(
                        "absolute top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r bg-ochre-500",
                        collapsed ? "-left-[10px]" : "left-0"
                      )}
                    />
                  )}
                  <Icon
                    className={cn(
                      "h-[18px] w-[18px] shrink-0 transition-colors",
                      isActive ? "text-ochre-400" : "text-white/55 group-hover:text-white"
                    )}
                  />
                  {!collapsed && <span className="truncate">{label}</span>}
                </>
              )}
            </NavLink>
          ))}
        </nav>

        {/* Footer hint — hidden when collapsed */}
        {!collapsed && (
          <div className="relative mt-4 overflow-hidden rounded-md bg-white/[0.04] p-4 ring-1 ring-white/[0.06]">
            <p className="font-display text-sm font-semibold text-white">
              Dr. Osoro's suite
            </p>
            <p className="mt-1 text-xs text-white/55">
              Rent collection, tenants & reports — all in one place.
            </p>
          </div>
        )}
      </div>
    </aside>
  );
}
