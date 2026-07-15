import { ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";

export interface Crumb {
  label: string;
  /** Omit `to` for the current (last) item. */
  to?: string;
}

/** Positional breadcrumb, e.g. Portfolio › Donholm › Mercy Murunga. */
export function Breadcrumb({ items }: { items: Crumb[] }) {
  return (
    <nav aria-label="Breadcrumb" className="mb-4">
      <ol className="flex flex-wrap items-center gap-1 text-sm text-content-muted">
        {items.map((item, i) => {
          const last = i === items.length - 1;
          return (
            <li key={i} className="flex items-center gap-1">
              {item.to && !last ? (
                <Link
                  to={item.to}
                  className="rounded px-1 text-content-muted transition-colors hover:text-content focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/40"
                >
                  {item.label}
                </Link>
              ) : (
                <span className={last ? "font-medium text-content" : "px-1"} aria-current={last ? "page" : undefined}>
                  {item.label}
                </span>
              )}
              {!last && <ChevronRight className="h-3.5 w-3.5 text-content-muted/60" aria-hidden />}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
