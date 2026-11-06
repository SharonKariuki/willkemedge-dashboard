import { ChevronDown, LogOut, Menu, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";

import { useAuth } from "@/hooks/useAuth";
import { useNavTree } from "@/hooks/useNavTree";
import { cn } from "@/lib/cn";
import { NAV_CHILDREN, childHref, isChildActive, isUnder, type NavItem, type ViewKey } from "@/lib/nav";

/** The four pages on the bottom bar; everything, these included, is in the Menu sheet. */
const PRIMARY_KEYS: ViewKey[] = ["dashboard", "units", "tenants", "payments"];

export default function MobileNav() {
  const [open, setOpen] = useState(false);
  const { pathname, search } = useLocation();
  const { logout } = useAuth();
  const { sections, footer, isOpen, toggle } = useNavTree({ remember: false });

  useEffect(() => {
    setOpen(false);
  }, [pathname, search]);

  useEffect(() => {
    document.body.style.overflow = open ? "hidden" : "";
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = "";
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const allItems = useMemo(() => [...sections.flatMap((s) => s.items), ...footer], [sections, footer]);
  const primaryItems = useMemo(
    () => PRIMARY_KEYS.map((k) => allItems.find((i) => i.key === k)).filter((i): i is NavItem => Boolean(i)),
    [allItems]
  );
  const menuActive = !primaryItems.some((i) => isUnder(i, pathname));

  const tile = (item: NavItem) => {
    const { to, label, icon: Icon } = item;
    return (
      <NavLink
        key={item.key}
        to={to}
        className={({ isActive }) =>
          cn(
            "flex min-h-[44px] items-center gap-3 rounded-md px-3 py-2.5 text-sm font-medium transition-colors",
            isActive ? "bg-ink-900 text-white shadow-float dark:bg-ink-100 dark:text-canvas" : "bg-surface-sunk text-content hover:bg-hover"
          )
        }
      >
        <Icon className="h-4 w-4 shrink-0" />
        <span className="truncate">{label}</span>
      </NavLink>
    );
  };

  const parent = (item: NavItem) => {
    const { label, icon: Icon } = item;
    const expanded = isOpen(item.key);
    const active = isUnder(item, pathname);
    const listId = `mobile-nav-children-${item.key}`;
    return (
      <div key={item.key} className="col-span-2">
        <button
          type="button"
          aria-expanded={expanded}
          aria-controls={listId}
          onClick={() => toggle(item.key)}
          className={cn(
            "flex min-h-[44px] w-full items-center gap-3 rounded-md px-3 py-2.5 text-sm font-medium transition-colors",
            active ? "bg-surface-sunk text-content ring-1 ring-ochre-500/40" : "bg-surface-sunk text-content hover:bg-hover"
          )}
        >
          <Icon className="h-4 w-4 shrink-0" />
          <span className="flex-1 truncate text-left">{label}</span>
          <ChevronDown
            aria-hidden
            className={cn("h-4 w-4 shrink-0 text-content-muted transition-transform duration-200", expanded && "rotate-180")}
          />
        </button>

        {expanded && (
          <div id={listId} className="ml-5 mt-1 border-l border-border pl-3">
            {NAV_CHILDREN[item.key]!.map((group, gi) => (
              <div key={group.label ?? gi}>
                {group.label && (
                  <p className="pb-1 pt-2.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-content-muted">
                    {group.label}
                  </p>
                )}
                <div className="grid grid-cols-2 gap-1">
                  {group.items.map((child) => {
                    const childActive = isChildActive(item, child, pathname, search);
                    return (
                      <Link
                        key={child.value}
                        to={childHref(item, child)}
                        aria-current={childActive ? "page" : undefined}
                        className={cn(
                          "flex min-h-[44px] items-center rounded-md px-2.5 text-[13px] leading-tight transition-colors",
                          childActive
                            ? "bg-ink-900 font-medium text-white dark:bg-ink-100 dark:text-canvas"
                            : "text-content-secondary hover:bg-hover hover:text-content"
                        )}
                      >
                        {child.label}
                      </Link>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  };

  const entry = (item: NavItem) => (NAV_CHILDREN[item.key] ? parent(item) : tile(item));

  return (
    <>
      {/* Bottom tab bar (mobile only) */}
      <nav
        aria-label="Primary"
        className="fixed inset-x-3 bottom-3 z-40 md:hidden"
        style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
      >
        <div className="glass-strong flex items-center justify-around rounded-xl px-2 py-2 ring-1 ring-ochre-500/15">
          {primaryItems.map(({ to, label, icon: Icon }) => (
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
              menuActive ? "text-ink-900" : "text-ink-500"
            )}
            aria-label="Menu"
            aria-expanded={open}
            aria-controls="mobile-nav-sheet"
          >
            <span
              className={cn(
                "flex h-9 w-9 items-center justify-center rounded-md transition-all",
                menuActive ? "bg-ink-900 text-white shadow-float" : ""
              )}
            >
              <Menu className="h-4 w-4" />
            </span>
            Menu
          </button>
        </div>
      </nav>

      {/* Menu sheet — the whole tree, so every page is reachable on a phone */}
      {open && (
        <>
          <button
            type="button"
            aria-label="Close menu"
            className="fixed inset-0 z-50 bg-ink-900/30 backdrop-blur-sm md:hidden"
            onClick={() => setOpen(false)}
          />
          <div
            id="mobile-nav-sheet"
            role="dialog"
            aria-modal="true"
            aria-label="Menu"
            className="fixed inset-x-0 bottom-0 z-50 flex max-h-[88vh] flex-col rounded-t-2xl border border-b-0 border-border bg-surface shadow-float supports-[height:100dvh]:max-h-[88dvh] md:hidden animate-fade-up"
          >
            <div className="flex shrink-0 items-center justify-between border-b border-border px-4 py-3">
              <p className="font-display text-base font-semibold text-content">Menu</p>
              <button
                type="button"
                onClick={() => setOpen(false)}
                aria-label="Close"
                className="flex h-9 w-9 items-center justify-center rounded-md text-content-muted hover:bg-hover hover:text-content"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <nav aria-label="All pages" className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 pb-2">
              {sections.map((section, i) => (
                <section key={section.label ?? i}>
                  {section.label && (
                    <p className="pb-1.5 pt-4 text-[10px] font-semibold uppercase tracking-[0.14em] text-content-muted">
                      {section.label}
                    </p>
                  )}
                  <div className={cn("grid grid-cols-2 gap-2", !section.label && "pt-3")}>
                    {section.items.map(entry)}
                  </div>
                </section>
              ))}
            </nav>

            <div
              className="grid shrink-0 grid-cols-2 gap-2 border-t border-border px-4 pt-3"
              style={{ paddingBottom: "max(env(safe-area-inset-bottom), 1rem)" }}
            >
              {footer.map(entry)}
              <button
                type="button"
                onClick={() => void logout()}
                className="flex min-h-[44px] items-center gap-3 rounded-md bg-surface-sunk px-3 py-2.5 text-sm font-medium text-content hover:bg-hover"
              >
                <LogOut className="h-4 w-4 shrink-0" />
                Sign out
              </button>
            </div>
          </div>
        </>
      )}
    </>
  );
}
