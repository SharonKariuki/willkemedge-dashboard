/**
 * TenantPicker — type-to-filter tenant selector for the reconciliation queue.
 *
 * A plain <select> of ninety-odd tenants meant scrolling to find one, and it
 * only carried the active ones — so a credit from a tenant who had given notice
 * could not be assigned at all. Elimisha's PesaLink payment hit exactly that.
 *
 * Filters across unit label, name and phone, because the narration on a bank
 * credit might name any of them. Non-active tenancies are included and labelled,
 * since a tenant on notice still owes rent and one who has moved out may still
 * be settling arrears.
 */
import { Check, ChevronDown, Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { Badge } from "@/components/ui";
import { matches, type TenantChoice } from "@/features/payments/tenantChoices";
import { cn } from "@/lib/cn";

export function TenantPicker({
  choices,
  value,
  onChange,
  disabled,
  suggestion,
  ariaLabel,
}: {
  choices: TenantChoice[];
  value: number | null;
  onChange: (id: number | null) => void;
  disabled?: boolean;
  /** Seeded from the payer name on the credit, so the list opens pre-narrowed. */
  suggestion?: string;
  ariaLabel: string;
}) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const boxRef = useRef<HTMLDivElement>(null);

  const selected = useMemo(
    () => choices.find((c) => c.id === value) ?? null,
    [choices, value],
  );

  const results = useMemo(() => {
    const filtered = choices.filter((c) => matches(c, query));
    // Cap the rendered list — ninety options is a scroll, not a choice. Typing
    // narrows it; the count below tells you when there is more.
    return { shown: filtered.slice(0, 50), total: filtered.length };
  }, [choices, query]);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  const openWith = (seed: string) => {
    setQuery(seed);
    setActive(0);
    setOpen(true);
  };

  const choose = (choice: TenantChoice) => {
    onChange(choice.id);
    setQuery("");
    setOpen(false);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!open) return openWith(query);
      const step = e.key === "ArrowDown" ? 1 : -1;
      setActive((i) => Math.max(0, Math.min(results.shown.length - 1, i + step)));
    } else if (e.key === "Enter") {
      if (open && results.shown[active]) {
        e.preventDefault();
        choose(results.shown[active]);
      }
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  return (
    <div ref={boxRef} className="relative min-w-[15rem]">
      <div className="relative">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-400" />
        <input
          type="text"
          role="combobox"
          aria-expanded={open}
          aria-controls={open ? `${ariaLabel}-listbox` : undefined}
          aria-label={ariaLabel}
          autoComplete="off"
          disabled={disabled}
          className={cn(
            "w-full rounded-md bg-surface-raised hairline py-2 pl-8 pr-7 text-sm text-ink-900",
            "focus:outline-none focus:ring-2 focus:ring-sage-500/40 disabled:opacity-60",
          )}
          placeholder={selected ? "" : "Search unit, name or phone…"}
          value={open ? query : selected ? `${selected.unitLabel} — ${selected.name}` : query}
          onChange={(e) => openWith(e.target.value)}
          onFocus={() => openWith(selected ? "" : (suggestion ?? ""))}
          onKeyDown={onKeyDown}
        />
        <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-400" />
      </div>

      {open && (
        <div
          id={`${ariaLabel}-listbox`}
          role="listbox"
          className="absolute z-20 mt-1 max-h-72 w-full overflow-y-auto rounded-md bg-surface-raised p-1 shadow-lg hairline"
        >
          {results.shown.length === 0 ? (
            <p className="px-2 py-3 text-xs text-ink-400">No tenant matches “{query}”.</p>
          ) : (
            <>
              {results.shown.map((c, i) => (
                <button
                  key={c.id}
                  type="button"
                  role="option"
                  aria-selected={c.id === value}
                  onMouseEnter={() => setActive(i)}
                  onClick={() => choose(c)}
                  className={cn(
                    "flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm",
                    i === active ? "bg-sage-500/10" : "",
                  )}
                >
                  <span className="w-16 shrink-0 font-mono text-[11px] text-ink-500">
                    {c.unitLabel || "—"}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-ink-900">{c.name}</span>
                  {c.status !== "active" && (
                    <Badge tone="neutral">{c.statusDisplay}</Badge>
                  )}
                  {c.id === value && <Check className="h-3.5 w-3.5 shrink-0 text-sage-600" />}
                </button>
              ))}
              {results.total > results.shown.length && (
                <p className="px-2 py-1.5 text-[11px] text-ink-400">
                  {results.total - results.shown.length} more — keep typing to narrow.
                </p>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
