import { AlertTriangle } from "lucide-react";
import type { ReactNode } from "react";

/** A standing note under a field, or a warning the owner must read. */
export function Note({ tone = "muted", children }: { tone?: "muted" | "warn"; children: ReactNode }) {
  return tone === "warn" ? (
    <p className="mt-3 flex items-start gap-1.5 rounded-md bg-warning-soft px-3 py-2.5 text-xs text-warning">
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <span>{children}</span>
    </p>
  ) : (
    <p className="mt-2 text-[11px] leading-relaxed text-ink-500">{children}</p>
  );
}
