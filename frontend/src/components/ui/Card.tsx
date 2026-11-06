import { forwardRef, type HTMLAttributes } from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/cn";

const card = cva(
  // Resting surface — a 1px hairline border plus a tight, light shadow, so
  // the edge stays crisp against the tinted page background.
  "relative rounded-2xl transition-all duration-200 ease-out",
  {
    variants: {
      variant: {
        // Elevated — default floating white surface
        elevated: "bg-surface border border-border shadow-sm",
        // Flat — quiet surface, hairline only (no float)
        flat: "bg-surface border border-border",
        // Sunk — recessed surface
        sunk: "bg-surface-sunk",
        // Legacy aliases → floating look
        glass: "bg-surface border border-border shadow-sm",
        "glass-strong": "bg-surface border border-border shadow-sm",
        neu: "bg-surface border border-border shadow-sm",
        "neu-sm": "bg-surface border border-border shadow-xs",
      },
      padding: {
        none: "",
        sm: "p-4 sm:p-5",
        md: "p-6",
        lg: "p-6 sm:p-8",
      },
      interactive: {
        true: "cursor-pointer hover:shadow-md hover:-translate-y-0.5",
        false: "",
      },
    },
    defaultVariants: {
      variant: "elevated",
      padding: "md",
      interactive: false,
    },
  }
);

export interface CardProps
  extends HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof card> {}

export const Card = forwardRef<HTMLDivElement, CardProps>(
  ({ className, variant, padding, interactive, ...props }, ref) => (
    <div
      ref={ref}
      className={cn(card({ variant, padding, interactive }), className)}
      {...props}
    />
  )
);
Card.displayName = "Card";

export function CardHeader({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("mb-5 flex items-start justify-between gap-3", className)} {...props} />;
}

export function CardTitle({ className, ...props }: HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h3
      className={cn("text-lg font-semibold leading-tight text-content", className)}
      {...props}
    />
  );
}

/** Small uppercase eyebrow label — for the muted label style cards used before. */
export function CardEyebrow({ className, ...props }: HTMLAttributes<HTMLParagraphElement>) {
  return (
    <p
      className={cn(
        "text-xs font-medium uppercase tracking-[0.08em] text-content-muted",
        className
      )}
      {...props}
    />
  );
}

export function CardBody({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("", className)} {...props} />;
}
