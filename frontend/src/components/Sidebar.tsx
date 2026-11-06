import { ChevronLeft, ChevronRight, LogOut } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";
import { Link, useLocation } from "react-router-dom";

import NavTree from "@/components/nav/NavTree";
import { useAuth } from "@/hooks/useAuth";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { useNavTree } from "@/hooks/useNavTree";
import { cn } from "@/lib/cn";
import { displayName } from "@/lib/displayName";
import { linkHref, navItem, type NavNode } from "@/lib/nav";

const STORAGE_KEY = "willkemedge-sidebar-collapsed";

type GroupNode = Extract<NavNode, { kind: "group" }>;

export default function Sidebar() {
  // Below lg the expanded rail costs 224px of a 768px viewport, which leaves
  // the tables and filters too little room to lay out. The rail stays there,
  // and expanding it floats the full menu over the page instead of pushing
  // the page aside; the saved preference applies from lg up.
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

  const [peek, setPeek] = useState(false);
  const overlay = !roomToExpand && peek;
  const collapsed = roomToExpand ? preferCollapsed : !peek;
  const toggle = () => (roomToExpand ? setPreferCollapsed((c) => !c) : setPeek((p) => !p));

  const { user, logout } = useAuth();
  const { tree, active, isOpen, toggle: toggleNode } = useNavTree();

  // On the icon rail a group opens a flyout beside it instead of growing the rail.
  const [flyout, setFlyout] = useState<{ node: GroupNode; anchor: DOMRect } | null>(null);
  const closeFlyout = useCallback(() => setFlyout(null), []);
  const { pathname, search } = useLocation();
  useEffect(closeFlyout, [pathname, search, collapsed, closeFlyout]);
  useEffect(() => setPeek(false), [pathname, search, roomToExpand]);

  useEffect(() => {
    if (!overlay) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setPeek(false);
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [overlay]);

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
        "hidden shrink-0 transition-[width] duration-300 ease-out md:sticky md:top-0 md:z-40 md:flex md:h-screen md:flex-col",
        collapsed || overlay ? "md:w-[72px]" : "md:w-64"
      )}
    >
      {overlay && (
        <button
          type="button"
          aria-label="Close sidebar"
          className="fixed inset-0 z-40 bg-ink-900/30 backdrop-blur-[2px]"
          onClick={() => setPeek(false)}
        />
      )}
      <div
        className={cn(
          "sidebar-shell flex h-full flex-col px-3 py-4",
          overlay ? "fixed inset-y-0 left-0 z-50 w-64 shadow-float animate-fade-up" : "relative"
        )}
      >
        {/* Collapse toggle — pill straddling the right divider, at every width.
            Below lg it floats the full menu over the page. */}
        <button
          type="button"
          onClick={toggle}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-expanded={!collapsed}
          className="absolute -right-3 top-1/2 z-10 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-full bg-teal-600 text-white shadow-md ring-2 ring-sidebar transition-all hover:scale-110 hover:bg-teal-500 focus-visible:outline-none focus-visible:ring-teal-500"
        >
          {collapsed ? <ChevronRight className="h-3.5 w-3.5" /> : <ChevronLeft className="h-3.5 w-3.5" />}
        </button>

        {/* The menu — scrolls internally so the profile stays pinned */}
        <nav
          aria-label="Main"
          className="sidebar-nav min-h-0 flex-1 overflow-y-auto overflow-x-hidden pt-1"
        >
          {collapsed ? (
            <Rail
              nodes={tree}
              active={active}
              openId={flyout?.node.id}
              onOpen={(node, anchor) =>
                setFlyout((f) => (f?.node.id === node.id ? null : { node, anchor }))
              }
            />
          ) : (
            <NavTree nodes={tree} active={active} isOpen={isOpen} onToggle={toggleNode} idPrefix="sidebar" />
          )}
        </nav>

        {/* Profile + sign out — pinned to the bottom */}
        <div className={cn("mt-3 flex shrink-0 items-center gap-3 border-t border-white/[0.06] pt-3", collapsed ? "flex-col" : "px-1.5")}>
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-ochre-500 text-xs font-semibold text-ink-900 ring-1 ring-ochre-600/40">
            {initials}
          </div>

          {!collapsed && (
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-white">{handle || "User"}</p>
              <p className="text-[10px] uppercase tracking-[0.14em] text-white/45">Admin</p>
            </div>
          )}

          <button
            type="button"
            onClick={() => void logout()}
            aria-label="Sign out"
            title="Sign out"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-white/55 transition-colors hover:bg-white/5 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/70"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </div>

      {flyout && (
        <Flyout node={flyout.node} anchor={flyout.anchor} onClose={closeFlyout}>
          <NavTree
            nodes={flyout.node.children}
            active={active}
            isOpen={isOpen}
            onToggle={toggleNode}
            onNavigate={closeFlyout}
            idPrefix="flyout"
          />
        </Flyout>
      )}
    </aside>
  );
}

/** The icon rail: one icon per top-level entry, each with a tooltip. */
function Rail({
  nodes,
  active,
  openId,
  onOpen,
}: {
  nodes: NavNode[];
  active: string[];
  openId: string | undefined;
  onOpen: (node: GroupNode, anchor: DOMRect) => void;
}) {
  const cell = (on: boolean) =>
    cn(
      "group relative flex h-10 w-full items-center justify-center rounded-lg outline-none transition-colors duration-150 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-teal-500/70",
      on ? "bg-white/[0.09] text-white" : "text-white/55 hover:bg-white/[0.05] hover:text-white"
    );
  const marker = <span aria-hidden className="absolute -left-3 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r-full bg-teal-500" />;

  return (
    <ul className="flex flex-col gap-1">
      {nodes.map((node) => {
        const on = active.includes(node.id);
        if (node.kind === "link") {
          const item = navItem(node.page);
          const Icon = node.icon ?? item.icon;
          const label = node.label ?? item.label;
          return (
            <li key={node.id}>
              <Link to={linkHref(node)} title={label} aria-label={label} aria-current={on ? "page" : undefined} className={cell(on)}>
                {on && marker}
                <Icon aria-hidden className={cn("h-[18px] w-[18px]", on && "text-teal-500")} />
              </Link>
            </li>
          );
        }
        if (node.kind !== "group") return null;
        const Icon = node.icon;
        const open = openId === node.id;
        return (
          <li key={node.id}>
            <button
              type="button"
              data-nav-parent={node.id}
              title={node.label}
              aria-label={node.label}
              aria-haspopup="true"
              aria-expanded={open}
              onClick={(e) => onOpen(node, e.currentTarget.getBoundingClientRect())}
              className={cn(cell(on || open))}
            >
              {on && marker}
              <Icon aria-hidden className={cn("h-[18px] w-[18px]", on && "text-teal-500")} />
            </button>
          </li>
        );
      })}
    </ul>
  );
}

/**
 * A group's contents on the icon rail, floated beside its icon. Portalled to
 * <body>: the rail scrolls (clipping anything absolute) and is sticky, which
 * traps any z-index inside it under the page. In the lower half of the screen
 * it grows upward so it never runs off the bottom.
 */
function Flyout({
  node,
  anchor,
  onClose,
  children,
}: {
  node: GroupNode;
  anchor: DOMRect;
  onClose: () => void;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLElement>(null);

  useLayoutEffect(() => {
    ref.current?.querySelector<HTMLElement>("a, button")?.focus();
  }, []);

  useEffect(() => {
    const trigger = document.querySelector<HTMLElement>(`[data-nav-parent="${node.id}"]`);
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
  }, [node.id, onClose]);

  const growUp = anchor.top > window.innerHeight / 2;
  const style: CSSProperties = growUp
    ? { left: anchor.right + 12, bottom: window.innerHeight - anchor.bottom, maxHeight: anchor.bottom - 12 }
    : { left: anchor.right + 12, top: anchor.top, maxHeight: window.innerHeight - anchor.top - 12 };

  return createPortal(
    <nav
      ref={ref}
      aria-label={node.label}
      style={style}
      className="sidebar-shell fixed z-50 flex w-60 flex-col overflow-y-auto rounded-xl border-0 p-2 shadow-float ring-1 ring-white/10 animate-fade-up"
    >
      <p className="px-2.5 pb-2 pt-1 text-[10.5px] font-semibold uppercase tracking-[0.1em] text-white/40">{node.label}</p>
      {children}
    </nav>,
    document.body
  );
}
