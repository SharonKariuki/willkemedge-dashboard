import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router-dom";

import { useAuth } from "@/hooks/useAuth";
import { useViewPreferences } from "@/hooks/useViewPreferences";
import {
  NAV_CHILDREN,
  NAV_FOOTER,
  NAV_SECTIONS,
  isUnder,
  navItem,
  type NavItem,
  type NavSection,
  type ViewKey,
} from "@/lib/nav";

const OPEN_KEY = "willkemedge-nav-open";

export interface VisibleSection extends Omit<NavSection, "keys"> {
  items: NavItem[];
}

function readOpen(): ViewKey[] {
  try {
    const raw = localStorage.getItem(OPEN_KEY);
    return raw ? (JSON.parse(raw) as ViewKey[]) : [];
  } catch {
    return [];
  }
}

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
      NAV_SECTIONS.map(({ label, keys }) => ({ label, items: keys.map(navItem).filter(shown) })).filter(
        (s) => s.items.length > 0
      ),
    [shown]
  );

  const footer = useMemo(() => NAV_FOOTER.map(navItem).filter(shown), [shown]);

  // Which parents are open is remembered across visits (desktop only: a phone
  // sheet starts folded so it opens short); the parent of the page
  // on screen is always open so the active child is never hidden.
  const [openKeys, setOpenKeys] = useState<ViewKey[]>(() => (remember ? readOpen() : []));

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

  useEffect(() => {
    if (activeParent) setOpenKeys((keys) => (keys.includes(activeParent) ? keys : [...keys, activeParent]));
  }, [activeParent]);

  const isOpen = useCallback((key: ViewKey) => openKeys.includes(key), [openKeys]);
  const toggle = useCallback(
    (key: ViewKey) => setOpenKeys((keys) => (keys.includes(key) ? keys.filter((k) => k !== key) : [...keys, key])),
    []
  );

  return { sections, footer, isOpen, toggle };
}
