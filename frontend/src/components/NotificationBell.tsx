/**
 * NotificationBell — top-navbar real-time alert dropdown.
 * Reuses the main dashboard query (same key) so there is only ONE API call.
 * Polls every 15 s in sync with the dashboard.
 */
import { AlertTriangle, Bell, Clock, Home, Wrench, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { useDashboard, type AlertType } from "@/hooks/useDashboard";
import { cn } from "@/lib/cn";

const ICON_MAP: Record<AlertType, React.ComponentType<{ className?: string }>> = {
  overdue:        AlertTriangle,
  partial:        Clock,
  move_out:       Home,
  expiring_lease: Clock,
  maintenance:    Wrench,
};

const TONE_MAP: Record<AlertType, string> = {
  overdue:        "text-status-unpaid bg-status-unpaid/10",
  partial:        "text-ochre-600 bg-ochre-500/10",
  move_out:       "text-peri-600 bg-peri-500/10",
  expiring_lease: "text-ochre-600 bg-ochre-500/10",
  maintenance:    "text-ink-600 bg-ink-100",
};

const PRIORITY_ORDER: AlertType[] = ["overdue", "move_out", "expiring_lease", "partial", "maintenance"];

function prioritySort(a: { type: AlertType }, b: { type: AlertType }) {
  return PRIORITY_ORDER.indexOf(a.type) - PRIORITY_ORDER.indexOf(b.type);
}

export default function NotificationBell() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Reuse the same dashboard query — zero extra HTTP calls
  const { data } = useDashboard();
  const alerts = [...(data?.alerts ?? [])].sort(prioritySort);
  const count = alerts.length;

  // Close on outside click
  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    if (open) document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        aria-label={`Notifications — ${count} alert${count !== 1 ? "s" : ""}`}
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "relative flex h-9 w-9 items-center justify-center rounded-md transition-all",
          "glass hover:shadow-float",
          open && "bg-ink-900/10",
        )}
      >
        <Bell className="h-4 w-4 text-ink-700 dark:text-white/80" />
        {count > 0 && (
          <span className="absolute right-1.5 top-1.5 flex h-4 w-4 items-center justify-center rounded-full bg-coral-500 text-[9px] font-bold text-white shadow animate-pulse">
            {count > 9 ? "9+" : count}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-[calc(100%+8px)] z-50 w-[340px] animate-fade-up rounded-xl bg-white shadow-float ring-1 ring-ink-100 dark:bg-ink-900 dark:ring-ink-700">
          {/* Header */}
          <div className="flex items-center justify-between border-b border-ink-100 px-4 py-3 dark:border-ink-700">
            <div className="flex items-center gap-2">
              <Bell className="h-4 w-4 text-ink-700 dark:text-white/70" />
              <p className="font-display text-sm font-semibold text-ink-900 dark:text-white">
                Alerts
              </p>
            </div>
            <div className="flex items-center gap-2">
              {count > 0 && (
                <span className="rounded-full bg-coral-500/15 px-2 py-0.5 text-[10px] font-semibold text-coral-600">
                  {count} active
                </span>
              )}
              <button
                onClick={() => setOpen(false)}
                className="rounded-md p-1 text-ink-400 hover:text-ink-700 dark:hover:text-white"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>

          {/* Body */}
          <div className="max-h-[360px] overflow-y-auto">
            {count === 0 ? (
              <div className="flex flex-col items-center gap-2 py-10 text-center">
                <div className="flex h-10 w-10 items-center justify-center rounded-full bg-sage-500/10">
                  <Bell className="h-5 w-5 text-sage-600" />
                </div>
                <p className="text-sm font-medium text-ink-900 dark:text-white">All clear!</p>
                <p className="max-w-[220px] text-xs text-ink-500">
                  No overdue tenants or outstanding issues right now.
                </p>
              </div>
            ) : (
              <ul className="divide-y divide-ink-100 dark:divide-ink-700">
                {alerts.map((a, i) => {
                  const Icon = ICON_MAP[a.type] ?? AlertTriangle;
                  const tone = TONE_MAP[a.type] ?? "text-ink-600 bg-ink-100";
                  return (
                    <li key={i} className="flex items-start gap-3 px-4 py-3 hover:bg-ink-50 dark:hover:bg-ink-800 transition-colors">
                      <span className={cn("mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full", tone)}>
                        <Icon className="h-3.5 w-3.5" />
                      </span>
                      <p className="text-[13px] leading-snug text-ink-800 dark:text-ink-200">
                        {a.message}
                      </p>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          {/* Footer */}
          <div className="flex items-center justify-between border-t border-ink-100 px-4 py-2.5 dark:border-ink-700">
            <Link
              to="/dashboard"
              onClick={() => setOpen(false)}
              className="text-xs font-medium text-sage-600 hover:text-sage-700 dark:text-sage-400"
            >
              View dashboard →
            </Link>
            {count > 0 && (
              <Link
                to="/tenants"
                onClick={() => setOpen(false)}
                className="text-xs font-medium text-coral-600 hover:text-coral-700"
              >
                Manage tenants →
              </Link>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
