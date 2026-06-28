import { useCallback, useEffect, useState } from "react";

import type { ViewKey } from "@/lib/nav";

const STORAGE_KEY = "willkemedge-view-prefs";

export type ViewPreferences = Record<ViewKey, boolean>;

const DEFAULTS: ViewPreferences = {
  dashboard: true,
  buildings: true,
  units: true,
  tenants: true,
  payments: true,
  reconciliation: true,
  expenses: true,
  accounting: true,
  notifications: true,
  reports: true,
  settings: true,
};

function read(): ViewPreferences {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULTS };
    const parsed = JSON.parse(raw) as Partial<ViewPreferences>;
    return { ...DEFAULTS, ...parsed, dashboard: true, settings: true };
  } catch {
    return { ...DEFAULTS };
  }
}

const listeners = new Set<(prefs: ViewPreferences) => void>();

function broadcast(prefs: ViewPreferences) {
  listeners.forEach((fn) => fn(prefs));
}

export function useViewPreferences() {
  const [prefs, setPrefs] = useState<ViewPreferences>(read);

  useEffect(() => {
    const onChange = (next: ViewPreferences) => setPrefs(next);
    listeners.add(onChange);

    const onStorage = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY) setPrefs(read());
    };
    window.addEventListener("storage", onStorage);

    return () => {
      listeners.delete(onChange);
      window.removeEventListener("storage", onStorage);
    };
  }, []);

  const setView = useCallback((key: ViewKey, enabled: boolean) => {
    setPrefs((prev) => {
      const next = { ...prev, [key]: enabled, dashboard: true, settings: true };
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      } catch {
        // ignore
      }
      broadcast(next);
      return next;
    });
  }, []);

  const resetViews = useCallback(() => {
    const next = { ...DEFAULTS };
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      // ignore
    }
    broadcast(next);
    setPrefs(next);
  }, []);

  return { prefs, setView, resetViews };
}
