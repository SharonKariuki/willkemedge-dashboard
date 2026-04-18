import { forwardRef, type InputHTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/cn";

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  leftIcon?: ReactNode;
  rightIcon?: ReactNode;
  variant?: "glass" | "neu" | "flat";
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ className, leftIcon, rightIcon, variant = "glass", ...props }, ref) => {
    const base = {
      glass: "glass",
      neu: "neu-inset",
      flat: "bg-surface-raised hairline",
    }[variant];

    return (
      <div className={cn("relative flex items-center rounded-md", base, className)}>
        {leftIcon && (
          <span className="pointer-events-none absolute left-3 flex items-center text-ink-400">
            {leftIcon}
          </span>
        )}
        <input
          ref={ref}
          className={cn(
            "w-full bg-transparent px-4 py-2.5 text-sm text-ink-900 placeholder:text-ink-400 focus:outline-none",
            leftIcon && "pl-10",
            rightIcon && "pr-10"
          )}
          {...props}
        />
        {rightIcon && (
          <span className="pointer-events-none absolute right-3 flex items-center text-ink-400">
            {rightIcon}
          </span>
        )}
      </div>
    );
  }
);
Input.displayName = "Input";
