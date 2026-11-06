import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router-dom";

import { useAuth } from "@/hooks/useAuth";
import { useViewPreferences } from "@/hooks/useViewPreferences";
import {
  NAV_CHILDREN,
  NAV_FOOTER,
  NAV_SECTIONS,
  groupKey,
  isUnder,
  navItem,
  type NavItem,
  type NavSection,
} from "@/lib/nav";

const OPEN_KEY = "willkemedge-nav-open";

export interface VisibleSection extends Omit<NavSection, "keys"> {
  items: NavItem[];
  /** Holds the page on screen; its heading is highlighted and it is kept open. */
  active: boolean;
}

/** Saved open keys, or null on a first visit. */
function readOpen(): string[] | null {
  try {
    const raw = localStorage.getItem(OPEN_KEY);
    return raw ? (JSON.parse(raw) as string[]) : null;
  } catch {
    return null;
  }
}

// On a first visit every group starts open, so nothing is hidden until the
// user chooses to fold it away; the nested parents start folded.
const ALL_GROUPS = NAV_SECTIONS.flatMap((s) => (s.label ? [groupKey(s.label)] : []));

/**
 * The menu as this user sees it — the single source for the desktop sidebar
 * and the mobile sheet, so a page can never be reachable on one and missing
 * from the other. Pages hidden in Settings and owner-only pages are dropped,
 * and so is any section left empty.
 */
export function useNavTree({ remember = true }: { remember?: boolean } = {}) {
  const { prefs } = useViewPreferences();
  const isOwner = Boolean(useAuth().user?.can_forgive_money);
  const { pathname } = useLocation();

  const shown = useCallback(
    (item: NavItem) => (!item.togglable || prefs[item.key]) && (!item.ownerOnly || isOwner),
    [prefs, isOwner]
  );

  const sections = useMemo<VisibleSection[]>(
    () =>
      NAV_SECTIONS.map(({ label, keys }) => {
        const items = keys.map(navItem).filter(shown);
        return { label, items, active: items.some((i) => isUnder(i, pathname)) };
      }).filter((s) => s.items.length > 0),
    [shown, pathname]
  );

  const footer = useMemo(() => NAV_FOOTER.map(navItem).filter(shown), [shown]);

  // Which groups and parents are open is remembered across visits (desktop
  // only: a phone sheet starts folded so it opens short). The group and the
  // parent holding the page on screen open themselves, so the active item is
  // never hidden.
  const [openKeys, setOpenKeys] = useState<string[]>(() => (remember ? readOpen() ?? ALL_GROUPS : []));

  useEffect(() => {
    if (!remember) return;
    try {
      localStorage.setItem(OPEN_KEY, JSON.stringify(openKeys));
    } catch {
      // ignore
    }
  }, [openKeys, remember]);

  const activeParent = useMemo(
    () => sections.flatMap((s) => s.items).find((i) => NAV_CHILDREN[i.key] && isUnder(i, pathname))?.key,
    [sections, pathname]
  );

  const activeGroup = sections.find((s) => s.active)?.label;

  useEffect(() => {
    const wanted = [activeGroup && groupKey(activeGroup), activeParent].filter((k): k is string => Boolean(k));
    if (wanted.length === 0) return;
    setOpenKeys((keys) => (wanted.every((k) => keys.includes(k)) ? keys : [...new Set([...keys, ...wanted])]));
  }, [activeGroup, activeParent]);

  const isOpen = useCallback((key: string) => openKeys.includes(key), [openKeys]);
  const toggle = useCallback(
    (key: string) => setOpenKeys((keys) => (keys.includes(key) ? keys.filter((k) => k !== key) : [...keys, key])),
    []
  );

  return { sections, footer, isOpen, toggle };
}
