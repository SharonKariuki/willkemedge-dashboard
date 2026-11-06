import { LogOut, Menu, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";

import NavTree from "@/components/nav/NavTree";
import { useAuth } from "@/hooks/useAuth";
import { useNavTree } from "@/hooks/useNavTree";
import { cn } from "@/lib/cn";
import { links, navItem, type ViewKey } from "@/lib/nav";

/** The four pages on the bottom bar; everything, these included, is in the drawer. */
const PRIMARY_KEYS: ViewKey[] = ["dashboard", "units", "tenants", "payments"];

export default function MobileNav() {
  const [open, setOpen] = useState(false);
  const { pathname, search } = useLocation();
  const { logout } = useAuth();
  const { tree, active, isOpen, toggle } = useNavTree();
  const menuButton = useRef<HTMLButtonElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);

  // Any navigation closes the drawer (a link to the page already on screen
  // closes it through onNavigate instead).
  useEffect(() => setOpen(false), [pathname, search]);

  useEffect(() => {
    if (!open) return;
    document.body.style.overflow = "hidden";
    closeButton.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("keydown", onKey);
    const trigger = menuButton.current;
    return () => {
      document.body.style.overflow = "";
      document.removeEventListener("keydown", onKey);
      trigger?.focus({ preventScroll: true });
    };
  }, [open]);

  // Only pages this user can see make the bar.
  const primary = useMemo(() => {
    const visible = new Set(links(tree).map((l) => l.page));
    return PRIMARY_KEYS.filter((k) => visible.has(k)).map(navItem);
  }, [tree]);
  const menuActive = !primary.some((i) => pathname === i.to || pathname.startsWith(`${i.to}/`));

  return (
    <>
      {/* Bottom tab bar (mobile only) */}
      <nav
        aria-label="Primary"
        className="fixed inset-x-3 bottom-3 z-40 md:hidden"
        style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
      >
        <div className="glass-strong flex items-center justify-around rounded-xl px-2 py-2 ring-1 ring-ochre-500/15">
          {primary.map(({ to, label, icon: Icon }) => (
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
            ref={menuButton}
            type="button"
            onClick={() => setOpen(true)}
            className={cn(
              "flex min-w-[56px] flex-col items-center gap-0.5 rounded-md px-2 py-1.5 text-[10px] font-medium transition-all",
              menuActive ? "text-ink-900" : "text-ink-500"
            )}
            aria-label="Menu"
            aria-expanded={open}
            aria-controls="mobile-nav-drawer"
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

      {/* Drawer — the whole tree from the left. Always mounted so it can slide;
          inert and invisible while shut. */}
      <div
        aria-hidden
        onClick={() => setOpen(false)}
        className={cn(
          "fixed inset-0 z-50 bg-ink-900/40 backdrop-blur-[2px] transition-opacity duration-200 motion-reduce:transition-none md:hidden",
          open ? "opacity-100" : "pointer-events-none opacity-0"
        )}
      />
      <div
        id="mobile-nav-drawer"
        role="dialog"
        aria-modal="true"
        aria-label="Menu"
        {...(open ? {} : { inert: "" })}
        className={cn(
          "sidebar-shell fixed inset-y-0 left-0 z-50 flex w-[min(20rem,86vw)] flex-col shadow-float transition-[transform,visibility] duration-300 ease-out motion-reduce:transition-none md:hidden",
          open ? "visible translate-x-0" : "invisible -translate-x-full"
        )}
      >
        <div
          className="flex shrink-0 items-center justify-between px-5 pb-2"
          style={{ paddingTop: "max(env(safe-area-inset-top), 1rem)" }}
        >
          <p className="text-[10.5px] font-semibold uppercase tracking-[0.14em] text-white/45">Menu</p>
          <button
            ref={closeButton}
            type="button"
            onClick={() => setOpen(false)}
            aria-label="Close menu"
            className="-mr-2 flex h-11 w-11 items-center justify-center rounded-lg text-white/60 transition-colors hover:bg-white/[0.06] hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/70"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <nav aria-label="All pages" className="sidebar-nav min-h-0 flex-1 overflow-y-auto overscroll-contain px-3 pb-3">
          <NavTree
            nodes={tree}
            active={active}
            isOpen={isOpen}
            onToggle={toggle}
            onNavigate={() => setOpen(false)}
            touch
            idPrefix="drawer"
          />
        </nav>

        <div
          className="shrink-0 border-t border-white/[0.06] px-3 pt-2"
          style={{ paddingBottom: "max(env(safe-area-inset-bottom), 0.75rem)" }}
        >
          <button
            type="button"
            onClick={() => void logout()}
            className="flex min-h-[44px] w-full items-center gap-3 rounded-lg px-2.5 text-[13.5px] font-medium text-white/70 transition-colors hover:bg-white/[0.05] hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-teal-500/70"
          >
            <LogOut aria-hidden className="h-[18px] w-[18px] text-white/45" />
            Sign out
          </button>
        </div>
      </div>
    </>
  );
}
