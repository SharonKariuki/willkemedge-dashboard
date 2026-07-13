import { ChevronLeft, ChevronRight, LogOut } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { NavLink } from "react-router-dom";

import { useAuth } from "@/hooks/useAuth";
import { useViewPreferences } from "@/hooks/useViewPreferences";
import { cn } from "@/lib/cn";
import { displayName } from "@/lib/displayName";
import { NAV_ITEMS } from "@/lib/nav";

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

  const { prefs } = useViewPreferences();
  const visibleItems = useMemo(
    () => NAV_ITEMS.filter((item) => !item.togglable || prefs[item.key]),
    [prefs]
  );

  const { user, logout } = useAuth();
  const handle = displayName(user?.email?.split("@")[0] ?? "");
  const initials =
    (handle || "??")
      .split(/[._\- ]/)
      .slice(0, 2)
      .map((s) => s[0]?.toUpperCase() ?? "")
      .join("") || "U";

  return (
    <aside
      className={cn(
        "hidden shrink-0 transition-[width] duration-300 ease-out md:sticky md:top-0 md:flex md:h-screen md:flex-col",
        collapsed ? "md:w-[72px]" : "md:w-56"
      )}
    >
      <div className="sidebar-shell relative flex h-full flex-col px-3 py-4">
        {/* Collapse toggle — pill straddling the right divider */}
        <button
          type="button"
          onClick={toggle}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className="absolute -right-3 top-7 z-10 flex h-7 w-7 items-center justify-center rounded-full bg-teal-600 text-white shadow-md ring-2 ring-sidebar transition-all hover:scale-110 hover:bg-teal-500"
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
            "flex shrink-0 items-center gap-3 border-b border-white/[0.06] pb-5 pt-1",
            collapsed ? "justify-center" : "px-3"
          )}
        >
          <div className="relative flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-ochre-500 text-ink-900 shadow-glass ring-1 ring-ochre-600/40">
            <span className="font-display text-lg font-semibold leading-none">W</span>
          </div>
        </div>

        {/* Primary nav — scrolls internally so the profile stays pinned */}
        <nav className="sidebar-nav flex min-h-0 flex-1 flex-col gap-1.5 overflow-y-auto pt-4">
          {visibleItems.map(({ to, label, icon: Icon }) => (
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

        {/* Profile + logout — pinned to the bottom */}
        <div
          className={cn(
            "mt-3 flex shrink-0 items-center gap-3 border-t border-white/[0.06] pt-4",
            collapsed ? "flex-col" : "px-3"
          )}
        >
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-ochre-500 text-xs font-semibold text-ink-900 ring-1 ring-ochre-600/40">
            {initials}
          </div>

          {!collapsed && (
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-white">
                {handle || "User"}
              </p>
              <p className="text-[10px] uppercase tracking-[0.14em] text-white/45">
                Admin
              </p>
            </div>
          )}

          <button
            type="button"
            onClick={() => void logout()}
            aria-label="Sign out"
            title="Sign out"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-white/55 transition-colors hover:bg-white/5 hover:text-white"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </div>
    </aside>
  );
}
