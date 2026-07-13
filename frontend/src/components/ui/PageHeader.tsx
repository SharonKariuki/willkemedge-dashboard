import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

interface Props {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
  className?: string;
}

export function PageHeader({ eyebrow, title, description, actions, className }: Props) {
  return (
    <div className={cn("mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between", className)}>
      <div className="min-w-0">
        {eyebrow && (
          <p className="text-xs font-semibold uppercase tracking-wider text-teal-700 dark:text-teal-600">
            {eyebrow}
          </p>
        )}
        <h1 className="mt-1.5 text-3xl font-bold leading-tight tracking-tight text-content">
          {title}
        </h1>
        {description && (
          <p className="mt-2 max-w-2xl text-base text-content-secondary">{description}</p>
        )}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2.5">{actions}</div>}
    </div>
  );
}
