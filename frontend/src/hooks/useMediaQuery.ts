import { useEffect, useState } from "react";

/**
 * Subscribes to a CSS media query. Use it only where a breakpoint changes what
 * is *rendered* (structure) rather than how it looks — anything purely visual
 * belongs in Tailwind's responsive classes, which cost no JS and no re-render.
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(
    () => typeof window !== "undefined" && window.matchMedia(query).matches
  );

  useEffect(() => {
    const mql = window.matchMedia(query);
    const onChange = (e: MediaQueryListEvent) => setMatches(e.matches);
    setMatches(mql.matches);
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, [query]);

  return matches;
}
