import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { Loader2 } from "lucide-react";

import { cn } from "@/lib/cn";

const button = cva(
  "inline-flex items-center justify-center gap-2 rounded-md font-medium transition-colors duration-150 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50 whitespace-nowrap focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-app",
  {
    variants: {
      variant: {
        // Primary — navy identity
        primary:
          "bg-navy-800 text-white shadow-xs hover:bg-navy-700",
        // Secondary — teal interactive
        secondary:
          "bg-teal-700 text-white shadow-xs hover:bg-teal-800",
        // Neutral outline (subtle secondary action)
        outline:
          "bg-surface text-content border border-border hover:bg-hover hover:border-border-strong",
        // Ghost — transparent with subtle hover
        ghost:
          "text-content-secondary hover:bg-hover hover:text-content",
        // Danger — destructive
        danger:
          "bg-danger text-white shadow-xs hover:brightness-105",
        // Legacy aliases (kept so existing call sites don't break)
        gold:
          "bg-teal-700 text-white shadow-xs hover:bg-teal-800",
        glass:
          "bg-surface text-content border border-border hover:bg-hover",
      },
      size: {
        sm: "h-8 px-3 text-sm",
        md: "h-10 px-4 text-base",
        lg: "h-11 px-5 text-md",
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
