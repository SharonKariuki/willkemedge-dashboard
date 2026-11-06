import { useCallback, useEffect, useMemo, useSyncExternalStore } from "react";
import { useLocation } from "react-router-dom";

import { useAuth } from "@/hooks/useAuth";
import { useViewPreferences } from "@/hooks/useViewPreferences";
import { NAV_TREE, activePath, navItem, type NavNode, type ViewKey } from "@/lib/nav";

const OPEN_KEY = "willkemedge-nav-open";

// Earlier menus saved their open sections under other ids. Carry them over so
// nobody finds their menu reset.
const LEGACY: Record<string, string[]> = {
  "group:Property": ["property"],
  "group:Money": ["finance"],
  "group:Books": ["finance", "reports"],
};

function readOpen(): string[] {
  try {
    const raw = localStorage.getItem(OPEN_KEY);
    const saved = raw ? (JSON.parse(raw) as string[]) : [];
    return [...new Set(saved.flatMap((k) => LEGACY[k] ?? [k]))];
  } catch {
    return [];
  }
}

// One open/closed state for the whole app: the sidebar and the phone drawer
// are both mounted (CSS decides which shows), and must agree.
let openKeys: string[] = readOpen();
const listeners = new Set<() => void>();

function setOpenKeys(next: string[]) {
  if (next === openKeys) return;
  openKeys = next;
  try {
    localStorage.setItem(OPEN_KEY, JSON.stringify(next));
  } catch {
    // ignore
  }
  listeners.forEach((l) => l());
}

const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => void listeners.delete(l);
};
const snapshot = () => openKeys;

/** Drops links the user cannot or chose not to see, then any group left empty. */
function prune(nodes: NavNode[], shown: (key: ViewKey) => boolean): NavNode[] {
  return nodes.flatMap((n): NavNode[] => {
    if (n.kind === "link") return shown(n.page) ? [n] : [];
    const children = prune(n.children, shown);
    return children.length ? [{ ...n, children }] : [];
  });
}

/**
 * The menu as this user sees it — the single source for the desktop sidebar,
 * the icon rail and the phone drawer. Owner-only pages and pages hidden in
 * Settings are dropped, and so is any group left empty. (Hiding a link is not
 * the access check: the server and the pages enforce that.)
 */
export function useNavTree() {
  const { prefs } = useViewPreferences();
  const isOwner = Boolean(useAuth().user?.can_forgive_money);
  const { pathname, search } = useLocation();

  const shown = useCallback(
    (key: ViewKey) => {
      const item = navItem(key);
      return (!item.togglable || prefs[key]) && (!item.ownerOnly || isOwner);
    },
    [prefs, isOwner]
  );

  const tree = useMemo(() => prune(NAV_TREE, shown), [shown]);

  /** The active link's id last, the groups above it before it. */
  const active = useMemo(() => activePath(tree, pathname, search), [tree, pathname, search]);

  const open = useSyncExternalStore(subscribe, snapshot);

  // The groups above the page on screen open themselves, so the active link is
  // never hidden. Nothing else is closed: what the user opened stays open.
  const ancestors = active.slice(0, -1).join("|");
  useEffect(() => {
    const wanted = ancestors ? ancestors.split("|") : [];
    if (wanted.some((k) => !openKeys.includes(k))) setOpenKeys([...new Set([...openKeys, ...wanted])]);
  }, [ancestors]);

  const isOpen = useCallback((id: string) => open.includes(id), [open]);
  const toggle = useCallback(
    (id: string) => setOpenKeys(openKeys.includes(id) ? openKeys.filter((k) => k !== id) : [...openKeys, id]),
    []
  );

  return { tree, active, isOpen, toggle };
}
