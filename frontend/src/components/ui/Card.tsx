import { forwardRef, type HTMLAttributes } from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/cn";

const card = cva(
  "relative rounded-lg transition-all duration-300 ease-out",
  {
    variants: {
      variant: {
        glass: "glass",
        "glass-strong": "glass-strong",
        neu: "neu",
        "neu-sm": "neu-sm",
        flat: "bg-surface-raised shadow-glass",
      },
      padding: {
        none: "",
        sm: "p-3 sm:p-4",
        md: "p-4 sm:p-5 md:p-6",
        lg: "p-5 sm:p-6 md:p-8",
      },
      interactive: {
        true: "cursor-pointer hover:-translate-y-0.5 hover:shadow-float",
        false: "",
      },
    },
    defaultVariants: {
      variant: "glass",
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
  return <div className={cn("mb-4 flex items-start justify-between gap-3", className)} {...props} />;
}

export function CardTitle({ className, ...props }: HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h3
      className={cn(
        "text-sm font-medium uppercase tracking-[0.14em] text-ink-500",
        className
      )}
      {...props}
    />
  );
}

export function CardBody({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("", className)} {...props} />;
}
