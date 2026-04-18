import type { HTMLAttributes } from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/cn";

const badge = cva(
  "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1",
  {
    variants: {
      tone: {
        neutral: "bg-ink-100 text-ink-700 ring-ink-200/70",
        sage: "bg-sage-50/70 text-sage-700 ring-sage-500/20 dark:bg-sage-700/20 dark:text-sage-400",
        coral: "bg-coral-50/60 text-coral-600 ring-coral-500/15 dark:bg-coral-500/15 dark:text-coral-400",
        ochre: "bg-ochre-50/70 text-ochre-600 ring-ochre-500/20 dark:bg-ochre-500/15 dark:text-ochre-400",
        peri: "bg-peri-50/70 text-peri-600 ring-peri-500/15 dark:bg-peri-500/15 dark:text-peri-400",
        paid: "bg-status-paid/10 text-status-paid ring-status-paid/20",
        partial: "bg-status-partial/15 text-status-partial ring-status-partial/25",
        unpaid: "bg-status-unpaid/10 text-status-unpaid ring-status-unpaid/20",
        vacant: "bg-status-vacant/15 text-status-vacant ring-status-vacant/25",
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
            tone === "paid" && "bg-status-paid",
            tone === "partial" && "bg-status-partial",
            tone === "unpaid" && "bg-status-unpaid",
            tone === "vacant" && "bg-status-vacant",
            tone === "sage" && "bg-sage-500",
            tone === "coral" && "bg-coral-500",
            tone === "ochre" && "bg-ochre-500",
            tone === "peri" && "bg-peri-500",
            (!tone || tone === "neutral") && "bg-ink-400"
          )}
        />
      )}
      {children}
    </span>
  );
}
