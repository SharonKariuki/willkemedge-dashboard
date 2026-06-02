import { AlertTriangle, RotateCw } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/cn";
import { Button } from "./Button";

interface Props {
  /** Calm, complete-sentence heading. */
  title?: string;
  /** Supporting sentence. */
  description?: string;
  /** Called when the reader chooses to try again. */
  onRetry?: () => void;
  icon?: ReactNode;
  className?: string;
}

/**
 * Shown when a data load fails. Editorial in tone: a quiet explanation and a
 * single way forward. Mirrors EmptyState's structure and spacing.
 */
export function ErrorState({
  title = "This view could not be loaded.",
  description = "The data did not come back. This is usually temporary — try again in a moment.",
  onRetry,
  icon,
  className,
}: Props) {
  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-lg px-6 py-12 text-center",
        className,
      )}
    >
      <div className="flex h-14 w-14 items-center justify-center rounded-full bg-status-unpaid/10 text-status-unpaid">
        {icon ?? <AlertTriangle className="h-5 w-5" />}
      </div>
      <div>
        <h3 className="font-display text-lg font-semibold text-ink-900">{title}</h3>
        {description && <p className="mt-1 max-w-md text-sm text-ink-500">{description}</p>}
      </div>
      {onRetry && (
        <div className="mt-2">
          <Button variant="glass" size="sm" onClick={onRetry}>
            <RotateCw className="h-3.5 w-3.5" /> Try again
          </Button>
        </div>
      )}
    </div>
  );
}
