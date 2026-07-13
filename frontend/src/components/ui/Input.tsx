import { forwardRef, type InputHTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/cn";

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  leftIcon?: ReactNode;
  rightIcon?: ReactNode;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ className, leftIcon, rightIcon, ...props }, ref) => {
    return (
      <div
        className={cn(
          "relative flex items-center rounded-md border border-border bg-surface transition-colors",
          "focus-within:border-teal-600 focus-within:ring-2 focus-within:ring-ring/25",
          className
        )}
      >
        {leftIcon && (
          <span className="pointer-events-none absolute left-3.5 flex items-center text-content-muted">
            {leftIcon}
          </span>
        )}
        <input
          ref={ref}
          className={cn(
            "w-full bg-transparent px-3.5 py-2.5 text-base text-content placeholder:text-content-muted focus:outline-none",
            leftIcon && "pl-10",
            rightIcon && "pr-10"
          )}
          {...props}
        />
        {rightIcon && (
          <span className="pointer-events-none absolute right-3.5 flex items-center text-content-muted">
            {rightIcon}
          </span>
        )}
      </div>
    );
  }
);
Input.displayName = "Input";
