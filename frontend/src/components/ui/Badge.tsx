import type { HTMLAttributes } from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/cn";

const badge = cva(
  "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset",
  {
    variants: {
      tone: {
        neutral: "bg-surface-sunk text-content-secondary ring-border",
        // teal / informational
        sage: "bg-info-soft text-teal-800 ring-teal-600/20 dark:text-teal-500",
        info: "bg-info-soft text-teal-800 ring-teal-600/20 dark:text-teal-500",
        // orange / attention
        coral: "bg-orange-500/10 text-orange-700 ring-orange-600/20 dark:text-orange-500",
        ochre: "bg-info-soft text-teal-800 ring-teal-600/20 dark:text-teal-500",
        peri: "bg-surface-sunk text-content-secondary ring-border",
        // semantic status
        paid: "bg-success-soft text-success ring-success/20",
        partial: "bg-warning-soft text-warning ring-warning/25",
        unpaid: "bg-danger-soft text-danger ring-danger/20",
        vacant: "bg-surface-sunk text-content-muted ring-border",
      },
      withDot: { true: "", false: "" },
    },
    defaultVariants: { tone: "neutral", withDot: false },
  }
);

interface BadgeProps extends HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badge> {}

export function Badge({ className, tone, withDot, children, ...props }: BadgeProps) {
  return (
    <span className={cn(badge({ tone, withDot }), className)} {...props}>
      {withDot && (
        <span
          className={cn(
            "inline-block h-1.5 w-1.5 rounded-full",
            tone === "paid" && "bg-success",
            tone === "partial" && "bg-warning",
            tone === "unpaid" && "bg-danger",
            tone === "vacant" && "bg-neutral-400",
            (tone === "sage" || tone === "info" || tone === "ochre") && "bg-teal-700",
            tone === "coral" && "bg-orange-600",
            tone === "peri" && "bg-neutral-400",
            (!tone || tone === "neutral") && "bg-neutral-400"
          )}
        />
      )}
      {children}
    </span>
  );
}
