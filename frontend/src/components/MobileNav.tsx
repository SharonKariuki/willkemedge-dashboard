import {
  BarChart3,
  Bell,
  Building2,
  CreditCard,
  Home,
  LayoutDashboard,
  MoreHorizontal,
  Receipt,
  Settings,
  Users,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";

import { cn } from "@/lib/cn";

const PRIMARY = [
  { to: "/dashboard", label: "Home", icon: LayoutDashboard },
  { to: "/units", label: "Units", icon: Home },
  { to: "/tenants", label: "Tenants", icon: Users },
  { to: "/payments", label: "Payments", icon: CreditCard },
];

const OVERFLOW = [
  { to: "/buildings", label: "Buildings", icon: Building2 },
  { to: "/expenses", label: "Expenses", icon: Receipt },
  { to: "/notifications", label: "Notifications", icon: Bell },
  { to: "/reports", label: "Reports", icon: BarChart3 },
  { to: "/settings", label: "Settings", icon: Settings },
];

export default function MobileNav() {
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();

  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  useEffect(() => {
    document.body.style.overflow = open ? "hidden" : "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [open]);

  const overflowActive = OVERFLOW.some((i) => pathname.startsWith(i.to));

  return (
    <>
      {/* Bottom tab bar (mobile only) */}
      <nav
        aria-label="Primary"
        className="fixed inset-x-3 bottom-3 z-40 lg:hidden"
        style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
      >
        <div className="glass-strong flex items-center justify-around rounded-xl px-2 py-2 ring-1 ring-ochre-500/15">
          {PRIMARY.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                cn(
                  "flex min-w-[56px] flex-col items-center gap-0.5 rounded-md px-2 py-1.5 text-[10px] font-medium transition-all",
                  isActive ? "text-ink-900" : "text-ink-500"
                )
              }
            >
              {({ isActive }) => (
                <>
                  <span
                    className={cn(
                      "flex h-9 w-9 items-center justify-center rounded-md transition-all",
                      isActive ? "bg-ink-900 text-white shadow-float" : "bg-transparent"
                    )}
                  >
                    <Icon className="h-4 w-4" />
                  </span>
                  {label}
                </>
              )}
            </NavLink>
          ))}

          <button
            type="button"
            onClick={() => setOpen(true)}
            className={cn(
              "flex min-w-[56px] flex-col items-center gap-0.5 rounded-md px-2 py-1.5 text-[10px] font-medium transition-all",
              overflowActive ? "text-ink-900" : "text-ink-500"
            )}
            aria-label="More"
          >
            <span
              className={cn(
                "flex h-9 w-9 items-center justify-center rounded-md transition-all",
                overflowActive ? "bg-ink-900 text-white shadow-float" : ""
              )}
            >
              <MoreHorizontal className="h-4 w-4" />
            </span>
            More
          </button>
        </div>
      </nav>

      {/* Overflow drawer */}
      {open && (
        <>
          <div
            className="fixed inset-0 z-50 bg-ink-900/30 backdrop-blur-sm lg:hidden"
            onClick={() => setOpen(false)}
          />
          <div
            className="glass-strong fixed inset-x-3 bottom-3 z-50 rounded-xl p-4 lg:hidden animate-fade-up"
            style={{ paddingBottom: "max(env(safe-area-inset-bottom), 1rem)" }}
          >
            <div className="mb-3 flex items-center justify-between">
              <p className="font-display text-base font-semibold text-ink-900">More</p>
              <button
                type="button"
                onClick={() => setOpen(false)}
                aria-label="Close"
                className="rounded-md p-1.5 text-ink-500 hover:bg-white/60 hover:text-ink-900 dark:hover:bg-white/5"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="grid grid-cols-2 gap-2">
              {OVERFLOW.map(({ to, label, icon: Icon }) => (
                <NavLink
                  key={to}
                  to={to}
                  className={({ isActive }) =>
                    cn(
                      "flex items-center gap-3 rounded-md px-3 py-3 text-sm font-medium transition-colors",
                      isActive
                        ? "bg-ink-900 text-white shadow-glass"
                        : "bg-white/60 text-ink-700 hover:bg-white/80"
                    )
                  }
                >
                  <Icon className="h-4 w-4" />
                  {label}
                </NavLink>
              ))}
            </div>
          </div>
        </>
      )}
    </>
  );
}
