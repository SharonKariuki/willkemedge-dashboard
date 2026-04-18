import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { Loader2 } from "lucide-react";

import { cn } from "@/lib/cn";

const button = cva(
  "inline-flex items-center justify-center gap-2 rounded-md font-medium transition-all active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50 whitespace-nowrap",
  {
    variants: {
      variant: {
        primary:
          "bg-ink-900 text-white shadow-glass hover:bg-ink-700 hover:shadow-float",
        gold:
          "bg-ochre-500 text-ink-900 shadow-glass ring-1 ring-ochre-600/40 hover:bg-ochre-400 hover:shadow-float",
        secondary:
          "bg-white text-ink-900 ring-1 ring-ink-200 hover:ring-ink-400",
        ghost:
          "text-ink-700 hover:bg-surface-raised/60 hover:text-ink-900",
        glass:
          "glass text-ink-900 hover:shadow-float",
        outline:
          "hairline bg-transparent text-ink-700 hover:bg-surface-raised/60",
        danger:
          "bg-status-unpaid text-white hover:brightness-110",
      },
      size: {
        sm: "h-8 px-3 text-xs",
        md: "h-10 px-4 text-sm",
        lg: "h-12 px-6 text-base",
        icon: "h-10 w-10",
        "icon-sm": "h-8 w-8",
      },
    },
    defaultVariants: {
      variant: "primary",
      size: "md",
    },
  }
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof button> {
  loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, loading, children, disabled, ...props }, ref) => (
    <button
      ref={ref}
      className={cn(button({ variant, size }), className)}
      disabled={disabled || loading}
      {...props}
    >
      {loading && <Loader2 className="h-4 w-4 animate-spin" />}
      {children}
    </button>
  )
);
Button.displayName = "Button";
