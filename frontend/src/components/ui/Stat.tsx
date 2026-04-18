import { useEffect, useState, type ReactNode } from "react";
import { ArrowDownRight, ArrowUpRight } from "lucide-react";

import { cn } from "@/lib/cn";
import { Card } from "./Card";

interface StatProps {
  label: string;
  value: number | string;
  prefix?: string;
  suffix?: string;
  delta?: number;
  deltaLabel?: string;
  icon?: ReactNode;
  tone?: "sage" | "coral" | "ochre" | "peri";
  variant?: "glass" | "neu";
  className?: string;
  animate?: boolean;
}

const TONE_RING: Record<NonNullable<StatProps["tone"]>, string> = {
  sage: "from-sage-400/30 to-sage-500/0",
  coral: "from-coral-400/30 to-coral-500/0",
  ochre: "from-ochre-400/30 to-ochre-500/0",
  peri: "from-peri-400/30 to-peri-500/0",
};

const TONE_ICON: Record<NonNullable<StatProps["tone"]>, string> = {
  sage: "bg-sage-50 text-sage-600 dark:bg-sage-700/20 dark:text-sage-400",
  coral: "bg-coral-50 text-coral-600 dark:bg-coral-500/15 dark:text-coral-400",
  ochre: "bg-ochre-50 text-ochre-600 dark:bg-ochre-500/15 dark:text-ochre-400",
  peri: "bg-peri-50 text-peri-600 dark:bg-peri-500/15 dark:text-peri-400",
};

function useCountUp(target: number, enabled: boolean, duration = 900) {
  const [val, setVal] = useState(enabled ? 0 : target);
  useEffect(() => {
    if (!enabled) {
      setVal(target);
      return;
    }
    const start = performance.now();
    let raf = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      // ease-out cubic
      const eased = 1 - Math.pow(1 - t, 3);
      setVal(target * eased);
      if (t < 1) raf = requestAnimationFrame(tick);
      else setVal(target);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, enabled, duration]);
  return val;
}

export function Stat({
  label,
  value,
  prefix,
  suffix,
  delta,
  deltaLabel,
  icon,
  tone = "sage",
  variant = "glass",
  className,
  animate = true,
}: StatProps) {
  const numeric = typeof value === "number" ? value : NaN;
  const shouldCount = animate && !Number.isNaN(numeric);
  const counted = useCountUp(Number.isNaN(numeric) ? 0 : numeric, shouldCount);
  const display = Number.isNaN(numeric)
    ? String(value)
    : Math.round(counted).toLocaleString();

  const positive = (delta ?? 0) >= 0;

  return (
    <Card variant={variant} padding="md" className={cn("relative overflow-hidden", className)}>
      <div
        aria-hidden
        className={cn(
          "pointer-events-none absolute -right-10 -top-10 h-40 w-40 rounded-full bg-gradient-to-br blur-2xl",
          TONE_RING[tone]
        )}
      />
      <div className="relative flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium uppercase tracking-[0.16em] text-ink-500">
            {label}
          </p>
          <p className="mt-2 font-display text-3xl font-semibold leading-none text-ink-900 sm:text-4xl">
            {prefix}
            <span className="tabular-nums">{display}</span>
            {suffix && <span className="ml-0.5 text-xl text-ink-500">{suffix}</span>}
          </p>
          {(delta !== undefined || deltaLabel) && (
            <div className="mt-3 flex items-center gap-1.5 text-xs">
              {delta !== undefined && (
                <span
                  className={cn(
                    "inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 font-medium",
                    positive
                      ? "bg-status-paid/10 text-status-paid"
                      : "bg-status-unpaid/10 text-status-unpaid"
                  )}
                >
                  {positive ? (
                    <ArrowUpRight className="h-3 w-3" />
                  ) : (
                    <ArrowDownRight className="h-3 w-3" />
                  )}
                  {Math.abs(delta).toFixed(1)}%
                </span>
              )}
              {deltaLabel && <span className="text-ink-500">{deltaLabel}</span>}
            </div>
          )}
        </div>
        {icon && (
          <div
            className={cn(
              "flex h-10 w-10 shrink-0 items-center justify-center rounded-md",
              TONE_ICON[tone]
            )}
          >
            {icon}
          </div>
        )}
      </div>
    </Card>
  );
}
