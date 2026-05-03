/**
 * DatePicker — reusable date input component used system-wide.
 * Wraps a native <input type="date"> with consistent styling.
 */
import { Calendar } from "lucide-react";
import { forwardRef } from "react";
import { cn } from "@/lib/cn";

interface DatePickerProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  className?: string;
  wrapperClassName?: string;
}

export const DatePicker = forwardRef<HTMLInputElement, DatePickerProps>(
  ({ label, error, className, wrapperClassName, ...props }, ref) => {
    return (
      <div className={wrapperClassName}>
        {label && (
          <label className="mb-1 block text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">
            {label}
          </label>
        )}
        <div className="relative">
          <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-400">
            <Calendar className="h-4 w-4" />
          </span>
          <input
            ref={ref}
            type="date"
            className={cn(
              "w-full rounded-md bg-surface-raised hairline pl-9 pr-3 py-2.5 text-sm text-ink-900",
              "placeholder:text-ink-400 focus:outline-none focus:ring-2 focus:ring-sage-500/40",
              "cursor-pointer",
              className,
            )}
            {...props}
          />
        </div>
        {error && <p className="mt-1 text-[11px] text-status-unpaid">{error}</p>}
      </div>
    );
  },
);

DatePicker.displayName = "DatePicker";
