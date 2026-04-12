/**
 * useTheme — manages light/dark mode.
 *
 * - Reads the saved preference from localStorage on mount.
 * - Falls back to the OS preference (prefers-color-scheme) if nothing is saved.
 * - Toggles the `dark` class on <html> so Tailwind's `darkMode: "class"` picks it up.
 * - Persists the chosen preference to localStorage.
 */
import { useEffect, useState } from "react";

type Theme = "light" | "dark";

const STORAGE_KEY = "willkemedge-theme";

function getInitialTheme(): Theme {
  try {
    const saved = localStorage.getItem(STORAGE_KEY) as Theme | null;
    if (saved === "light" || saved === "dark") return saved;
  } catch {
    // localStorage unavailable (SSR / private browsing edge cases)
  }
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function applyTheme(theme: Theme) {
  const root = document.documentElement;
  if (theme === "dark") {
    root.classList.add("dark");
  } else {
    root.classList.remove("dark");
  }
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(getInitialTheme);

  useEffect(() => {
    applyTheme(theme);
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      // ignore
    }
  }, [theme]);

  const toggle = () => setTheme((t) => (t === "dark" ? "light" : "dark"));

  return { theme, toggle, isDark: theme === "dark" };
}
