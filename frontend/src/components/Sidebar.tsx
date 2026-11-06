import { ChevronDown, ChevronLeft, ChevronRight, LogOut } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";
import { Link, NavLink, useLocation } from "react-router-dom";

import { useAuth } from "@/hooks/useAuth";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { useNavTree } from "@/hooks/useNavTree";
import { cn } from "@/lib/cn";
import { displayName } from "@/lib/displayName";
import { NAV_CHILDREN, childHref, isChildActive, isUnder, type NavItem } from "@/lib/nav";

const STORAGE_KEY = "willkemedge-sidebar-collapsed";

export default function Sidebar() {
  // Below lg the expanded rail costs 224px of a 768px viewport, which leaves
  // the tables and filters too little room to lay out. Force the icon rail
  // there; the saved preference applies from lg up.
  const roomToExpand = useMediaQuery("(min-width: 1024px)");

  const [preferCollapsed, setPreferCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) === "1";
    } catch {
      return false;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, preferCollapsed ? "1" : "0");
    } catch {
      // ignore
    }
  }, [preferCollapsed]);

  const collapsed = preferCollapsed || !roomToExpand;
  const toggle = () => setPreferCollapsed((c) => !c);

  const { user, logout } = useAuth();
  const { sections, footer, isOpen, toggle: toggleParent } = useNavTree();

  // On the icon rail a parent opens a flyout beside it instead of growing the rail.
  const [flyout, setFlyout] = useState<{ item: NavItem; anchor: DOMRect } | null>(null);
  const closeFlyout = useCallback(() => setFlyout(null), []);
  const { pathname, search } = useLocation();
  useEffect(closeFlyout, [pathname, search, collapsed, closeFlyout]);

  const handle = displayName(user?.email?.split("@")[0] ?? "");
  const initials =
    (handle || "??")
      .split(/[._\- ]/)
      .slice(0, 2)
      .map((s) => s[0]?.toUpperCase() ?? "")
      .join("") || "U";

  const renderItem = (item: NavItem) =>
    NAV_CHILDREN[item.key] ? (
      <ParentItem
        key={item.key}
        item={item}
        collapsed={collapsed}
        open={collapsed ? flyout?.item.key === item.key : isOpen(item.key)}
        onToggle={(anchor) =>
          collapsed
            ? setFlyout((f) => (f?.item.key === item.key ? null : { item, anchor }))
            : toggleParent(item.key)
        }
      />
    ) : (
      <LeafItem key={item.key} item={item} collapsed={collapsed} />
    );

  return (
    <aside
      className={cn(
        "hidden shrink-0 transition-[width] duration-300 ease-out md:sticky md:top-0 md:flex md:h-screen md:flex-col",
        collapsed ? "md:w-[72px]" : "md:w-56"
      )}
    >
      <div className="sidebar-shell relative flex h-full flex-col px-3 py-4">
        {/* Collapse toggle — pill straddling the right divider. Hidden below lg,
            where the rail is the only layout that leaves room for the page. */}
        <button
          type="button"
          onClick={toggle}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className="absolute -right-3 top-1/2 z-10 hidden h-7 w-7 -translate-y-1/2 items-center justify-center rounded-full bg-teal-600 text-white shadow-md ring-2 ring-sidebar transition-all hover:scale-110 hover:bg-teal-500 lg:flex"
        >
          {collapsed ? (
            <ChevronRight className="h-3.5 w-3.5" />
          ) : (
            <ChevronLeft className="h-3.5 w-3.5" />
          )}
        </button>

        {/* Primary nav — scrolls internally so the profile stays pinned */}
        <nav
          aria-label="Main"
          className="sidebar-nav flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto overflow-x-hidden pt-1"
        >
          {sections.map((section, i) => (
            <div key={section.label ?? i} className="flex flex-col gap-1">
              {section.label &&
                (collapsed ? (
                  <div aria-hidden className="mx-2 my-1.5 h-px bg-white/[0.08]" />
                ) : (
                  <p className="px-3 pb-0.5 pt-3 text-[10px] font-semibold uppercase tracking-[0.14em] text-white/35">
                    {section.label}
                  </p>
                ))}
              {section.items.map(renderItem)}
            </div>
          ))}
        </nav>

        {/* Activity, settings, profile + logout — pinned to the bottom */}
        <div className="mt-3 flex shrink-0 flex-col gap-1 border-t border-white/[0.06] pt-3">
          {footer.map(renderItem)}

          <div className={cn("mt-2 flex items-center gap-3", collapsed ? "flex-col" : "px-3")}>
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
      </div>

      {flyout && <Flyout item={flyout.item} anchor={flyout.anchor} onClose={closeFlyout} />}
    </aside>
  );
}

function ActiveBar({ collapsed }: { collapsed: boolean }) {
  return (
    <span
      className={cn(
        "absolute top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r bg-ochre-500",
        collapsed ? "-left-[10px]" : "left-0"
      )}
    />
  );
}

const rowClass = (collapsed: boolean, active: boolean) =>
  cn(
    "group relative flex w-full items-center gap-3 rounded-md py-2.5 text-sm font-medium transition-all",
    collapsed ? "justify-center px-2" : "px-3",
    active ? "bg-ochre-500/12 text-white" : "text-white/65 hover:bg-white/5 hover:text-white"
  );

const iconClass = (active: boolean) =>
  cn(
    "h-[18px] w-[18px] shrink-0 transition-colors",
    active ? "text-ochre-400" : "text-white/55 group-hover:text-white"
  );

function LeafItem({ item, collapsed }: { item: NavItem; collapsed: boolean }) {
  const { to, label, icon: Icon } = item;
  return (
    <NavLink to={to} title={collapsed ? label : undefined} className={({ isActive }) => rowClass(collapsed, isActive)}>
      {({ isActive }) => (
        <>
          {isActive && <ActiveBar collapsed={collapsed} />}
          <Icon className={iconClass(isActive)} />
          {!collapsed && <span className="truncate">{label}</span>}
        </>
      )}
    </NavLink>
  );
}

function ParentItem({
  item,
  collapsed,
  open,
  onToggle,
}: {
  item: NavItem;
  collapsed: boolean;
  open: boolean;
  onToggle: (anchor: DOMRect) => void;
}) {
  const { pathname } = useLocation();
  const active = isUnder(item, pathname);
  const { label, icon: Icon } = item;
  const listId = `nav-children-${item.key}`;

  return (
    <div>
      <button
        type="button"
        data-nav-parent={item.key}
        title={collapsed ? label : undefined}
        aria-label={collapsed ? label : undefined}
        aria-expanded={open}
        aria-controls={collapsed ? undefined : listId}
        onClick={(e) => onToggle(e.currentTarget.getBoundingClientRect())}
        className={rowClass(collapsed, active)}
      >
        {active && <ActiveBar collapsed={collapsed} />}
        <Icon className={iconClass(active)} />
        {collapsed ? (
          <ChevronRight aria-hidden className="absolute right-0.5 h-3 w-3 text-white/35" />
        ) : (
          <>
            <span className="flex-1 truncate text-left">{label}</span>
            <ChevronDown
              aria-hidden
              className={cn("h-4 w-4 shrink-0 text-white/40 transition-transform duration-200", open && "rotate-180")}
            />
          </>
        )}
      </button>

      {!collapsed && open && (
        <div id={listId} className="ml-[21px] mt-0.5 border-l border-white/[0.08] pb-1 pl-2">
          <ChildLinks item={item} />
        </div>
      )}
    </div>
  );
}

function ChildLinks({ item }: { item: NavItem }) {
  const { pathname, search } = useLocation();
  return (
    <>
      {NAV_CHILDREN[item.key]!.map((group, gi) => (
        <div key={group.label ?? gi} className="flex flex-col">
          {group.label && (
            <p className="px-2.5 pb-0.5 pt-2.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-white/30">
              {group.label}
            </p>
          )}
          {group.items.map((child) => {
            const active = isChildActive(item, child, pathname, search);
            return (
              <Link
                key={child.value}
                to={childHref(item, child)}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "truncate rounded-md px-2.5 py-1.5 text-[13px] transition-colors",
                  active ? "bg-white/[0.07] font-medium text-ochre-300" : "text-white/55 hover:bg-white/5 hover:text-white"
                )}
              >
                {child.label}
              </Link>
            );
          })}
        </div>
      ))}
    </>
  );
}

/**
 * The children of a parent on the icon rail, floated beside its icon. Portalled
 * to <body>: the rail scrolls (clipping anything absolute) and is sticky, which
 * traps any z-index inside it under the page. In the lower half of the screen
 * it grows upward so it never runs off the bottom.
 */
function Flyout({ item, anchor, onClose }: { item: NavItem; anchor: DOMRect; onClose: () => void }) {
  const ref = useRef<HTMLElement>(null);

  useLayoutEffect(() => {
    ref.current?.querySelector<HTMLElement>("a")?.focus();
  }, []);

  useEffect(() => {
    const trigger = document.querySelector<HTMLElement>(`[data-nav-parent="${item.key}"]`);
    const onPointer = (e: PointerEvent) => {
      const target = e.target as Node;
      if (!ref.current?.contains(target) && !trigger?.contains(target)) onClose();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        trigger?.focus();
      }
    };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    window.addEventListener("resize", onClose);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", onClose);
    };
  }, [item.key, onClose]);

  const growUp = anchor.top > window.innerHeight / 2;
  const style: CSSProperties = growUp
    ? { left: anchor.right + 10, bottom: window.innerHeight - anchor.bottom, maxHeight: anchor.bottom - 12 }
    : { left: anchor.right + 10, top: anchor.top, maxHeight: window.innerHeight - anchor.top - 12 };

  return createPortal(
    <nav
      ref={ref}
      aria-label={item.label}
      style={style}
      className="sidebar-shell fixed z-50 flex w-56 flex-col overflow-y-auto rounded-lg p-2 shadow-float ring-1 ring-white/10 animate-fade-up"
    >
      <p className="px-2.5 pb-1 pt-1 text-xs font-semibold text-white">{item.label}</p>
      <ChildLinks item={item} />
    </nav>,
    document.body
  );
}
