/**
 * Quick actions - the everyday jobs one click from any page. Each person
 * sees only what their access allows, so a caretaker's list is water and
 * maintenance and the owner's starts with inviting someone.
 */
import {
  Droplets, FileDown, History, type LucideIcon, Plus, Receipt, Send, Sprout, UserPlus, UserRoundPlus, Wallet, Wrench,
} from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "@/hooks/useAuth";
import { CAP, type Capability, can } from "@/lib/access";
import { cn } from "@/lib/cn";

interface QuickAction {
  label: string;
  hint?: string;
  to: string;
  needs: Capability;
  icon: LucideIcon;
  group: "Admin" | "Money" | "Properties";
}

const QUICK_ACTIONS: QuickAction[] = [
  { group: "Admin", label: "Invite someone", to: "/users?invite=1", needs: CAP.MANAGE_USERS, icon: UserPlus },
  { group: "Admin", label: "Activity log", to: "/activity", needs: CAP.VIEW_ACTIVITY, icon: History },
  { group: "Money", label: "Record a payment", hint: "Or split one across tenancies",
    to: "/payments?new=1", needs: CAP.RECORD_MONEY, icon: Wallet },
  { group: "Money", label: "Record an expense", to: "/expenses?new=1", needs: CAP.RECORD_MONEY, icon: Receipt },
  { group: "Money", label: "Record other income", to: "/income?new=1", needs: CAP.RECORD_MONEY, icon: Sprout },
  { group: "Money", label: "Send reminders", to: "/notifications", needs: CAP.SEND_MESSAGES, icon: Send },
  { group: "Money", label: "Download a report", to: "/reports", needs: CAP.VIEW_FINANCE, icon: FileDown },
  { group: "Properties", label: "Add a tenant", to: "/tenants?new=1", needs: CAP.MANAGE_PROPERTY, icon: UserRoundPlus },
  { group: "Properties", label: "Capture water readings", to: "/water", needs: CAP.RECORD_WATER, icon: Droplets },
  { group: "Properties", label: "Log maintenance", hint: "Open the unit, then Maintenance",
    to: "/buildings", needs: CAP.LOG_MAINTENANCE, icon: Wrench },
];

export default function QuickActions() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const menuId = useId();
  const wrap = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const items = useRef<(HTMLButtonElement | null)[]>([]);

  const actions = QUICK_ACTIONS.filter((a) => can(user, a.needs));
  const groups = (["Admin", "Money", "Properties"] as const)
    .map((g) => ({ name: g, actions: actions.filter((a) => a.group === g) }))
    .filter((g) => g.actions.length);

  useEffect(() => {
    if (!open) return;
    items.current[0]?.focus();
    const onDown = (e: MouseEvent) => {
      if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  if (!actions.length) return null;

  const go = (to: string) => {
    setOpen(false);
    navigate(to);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    const list = items.current.filter(Boolean) as HTMLButtonElement[];
    const i = list.indexOf(document.activeElement as HTMLButtonElement);
    if (e.key === "Escape") {
      setOpen(false);
      button.current?.focus();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      list[(i + 1) % list.length]?.focus();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      list[(i - 1 + list.length) % list.length]?.focus();
    }
  };

  let n = 0;
  return (
    <div ref={wrap} className="relative">
      <button
        ref={button}
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        className="flex items-center gap-1.5 rounded-full bg-teal-600 px-3 py-1.5 text-sm font-medium text-white shadow-sm transition-colors hover:bg-teal-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/60"
      >
        <Plus className="h-4 w-4" />
        <span className="hidden sm:inline">Quick actions</span>
        <span className="sr-only sm:hidden">Quick actions</span>
      </button>

      {open && (
        <div
          id={menuId}
          role="menu"
          aria-label="Quick actions"
          tabIndex={-1}
          onKeyDown={onKeyDown}
          className="absolute right-0 z-50 mt-2 w-72 overflow-hidden rounded-lg border border-border bg-surface py-1.5 shadow-float"
        >
          {groups.map((g) => (
            <div key={g.name} role="group" aria-label={g.name} className="py-1">
              <p className="px-3 pb-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-content-muted">{g.name}</p>
              {g.actions.map((a) => {
                const index = n++;
                const Icon = a.icon;
                return (
                  <button
                    key={a.label}
                    ref={(el) => { items.current[index] = el; }}
                    type="button"
                    role="menuitem"
                    onClick={() => go(a.to)}
                    className={cn(
                      "flex w-full items-start gap-2.5 px-3 py-2 text-left text-sm text-content",
                      "hover:bg-hover focus:bg-hover focus:outline-none",
                    )}
                  >
                    <Icon className="mt-0.5 h-4 w-4 shrink-0 text-teal-600" />
                    <span>
                      {a.label}
                      {a.hint && <span className="block text-xs text-content-muted">{a.hint}</span>}
                    </span>
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
