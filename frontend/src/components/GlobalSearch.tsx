import { useEffect, useMemo, useRef, useState } from "react";
import { Building2, DoorOpen, Search, User } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { useBuildings } from "@/hooks/useBuildings";
import { useTenants } from "@/hooks/useTenants";
import { useUnits } from "@/hooks/useUnits";
import { cn } from "@/lib/cn";

type ResultKind = "tenant" | "unit" | "building";

interface Result {
  kind: ResultKind;
  id: number;
  title: string;
  subtitle: string;
  to: string;
}

export default function GlobalSearch() {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  const { data: tenants } = useTenants();
  const { data: units } = useUnits();
  const { data: buildings } = useBuildings();

  const results = useMemo<Result[]>(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    const out: Result[] = [];

    (tenants ?? []).forEach((t) => {
      const hay =
        `${t.full_name} ${t.phone} ${t.unit_label} ${t.building_name}`.toLowerCase();
      if (hay.includes(q)) {
        out.push({
          kind: "tenant",
          id: t.id,
          title: t.full_name,
          subtitle: `${t.unit_label} · ${t.building_name}`,
          to: `/tenants?q=${encodeURIComponent(t.full_name)}`,
        });
      }
    });

    (units ?? []).forEach((u) => {
      const hay = `${u.label} ${u.building_name} ${u.unit_type}`.toLowerCase();
      if (hay.includes(q)) {
        out.push({
          kind: "unit",
          id: u.id,
          title: u.label,
          subtitle: `${u.building_name} · ${u.status_display}`,
          to: `/units?q=${encodeURIComponent(u.label)}`,
        });
      }
    });

    (buildings ?? []).forEach((b) => {
      const hay = `${b.name} ${b.address}`.toLowerCase();
      if (hay.includes(q)) {
        out.push({
          kind: "building",
          id: b.id,
          title: b.name,
          subtitle: b.address || `${b.unit_count} units`,
          to: `/buildings?q=${encodeURIComponent(b.name)}`,
        });
      }
    });

    return out.slice(0, 12);
  }, [query, tenants, units, buildings]);

  useEffect(() => {
    setActiveIndex(0);
  }, [results]);

  useEffect(() => {
    const onDocClick = (e: MouseEvent) => {
      if (!containerRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        inputRef.current?.focus();
        setOpen(true);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const go = (r: Result) => {
    navigate(r.to);
    setOpen(false);
    setQuery("");
    inputRef.current?.blur();
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape") {
      setOpen(false);
      inputRef.current?.blur();
      return;
    }
    if (!results.length) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => (i + 1) % results.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => (i - 1 + results.length) % results.length);
    } else if (e.key === "Enter") {
      e.preventDefault();
      const r = results[activeIndex];
      if (r) go(r);
    }
  };

  const iconFor = (kind: ResultKind) => {
    if (kind === "tenant") return <User className="h-3.5 w-3.5 text-ink-500" />;
    if (kind === "unit") return <DoorOpen className="h-3.5 w-3.5 text-ink-500" />;
    return <Building2 className="h-3.5 w-3.5 text-ink-500" />;
  };

  return (
    <div ref={containerRef} className="relative hidden min-w-0 max-w-xs flex-1 sm:block">
      <div className="glass flex items-center gap-2 rounded-md px-3 py-1.5 text-sm">
        <Search className="h-4 w-4 text-ink-400" />
        <input
          ref={inputRef}
          type="search"
          placeholder="Search tenants, units…"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
          className="w-full bg-transparent text-sm text-ink-900 placeholder:text-ink-400 focus:outline-none"
        />
        <kbd className="hidden rounded bg-ink-100 px-1.5 py-0.5 text-[10px] text-ink-500 md:inline">
          ⌘K
        </kbd>
      </div>

      {open && query.trim() && (
        <div className="glass absolute left-0 right-0 top-full z-40 mt-1 max-h-80 overflow-y-auto rounded-md py-1 text-sm shadow-float">
          {results.length === 0 ? (
            <div className="px-3 py-2 text-xs text-ink-500">No matches</div>
          ) : (
            results.map((r, i) => (
              <button
                key={`${r.kind}-${r.id}`}
                type="button"
                onMouseDown={(e) => {
                  e.preventDefault();
                  go(r);
                }}
                onMouseEnter={() => setActiveIndex(i)}
                className={cn(
                  "flex w-full items-center gap-2 px-3 py-1.5 text-left",
                  i === activeIndex ? "bg-ink-100/60" : "hover:bg-ink-100/40"
                )}
              >
                {iconFor(r.kind)}
                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs font-medium text-ink-900">{r.title}</p>
                  <p className="truncate text-[11px] text-ink-500">{r.subtitle}</p>
                </div>
                <span className="text-[10px] uppercase tracking-wider text-ink-400">
                  {r.kind}
                </span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
