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
  const [expanded, setExpanded] = useState(false);
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
      if (!containerRef.current?.contains(e.target as Node)) {
        setOpen(false);
        if (!query.trim()) setExpanded(false);
      }
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [query]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setExpanded(true);
        setOpen(true);
        requestAnimationFrame(() => inputRef.current?.focus());
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const openSearch = () => {
    setExpanded(true);
    requestAnimationFrame(() => inputRef.current?.focus());
  };

  const go = (r: Result) => {
    navigate(r.to);
    setOpen(false);
    setExpanded(false);
    setQuery("");
    inputRef.current?.blur();
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape") {
      setOpen(false);
      setExpanded(false);
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
    if (kind === "tenant") return <User className="h-3.5 w-3.5 text-content-muted" />;
    if (kind === "unit") return <DoorOpen className="h-3.5 w-3.5 text-content-muted" />;
    return <Building2 className="h-3.5 w-3.5 text-content-muted" />;
  };

  return (
    <div ref={containerRef} className="relative">
      {expanded ? (
        <div className="flex w-52 items-center gap-2 rounded-full border border-border bg-surface px-3.5 py-2 shadow-xs transition-all sm:w-64">
          <Search className="h-4 w-4 shrink-0 text-content-muted" />
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
            className="w-full bg-transparent text-sm text-content placeholder:text-content-muted focus:outline-none"
          />
          <kbd className="hidden rounded bg-surface-sunk px-1.5 py-0.5 text-[10px] text-content-muted md:inline">
            ⌘K
          </kbd>
        </div>
      ) : (
        <button
          type="button"
          onClick={openSearch}
          aria-label="Search"
          className="flex h-9 w-9 items-center justify-center rounded-full text-content-secondary transition-colors hover:bg-hover hover:text-content"
        >
          <Search className="h-[18px] w-[18px]" />
        </button>
      )}

      {expanded && open && query.trim() && (
        <div className="absolute right-0 top-full z-40 mt-2 max-h-80 w-72 overflow-y-auto rounded-xl border border-border bg-surface py-1.5 text-sm shadow-lg">
          {results.length === 0 ? (
            <div className="px-3.5 py-2.5 text-xs text-content-muted">No matches</div>
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
                  "flex w-full items-center gap-2.5 px-3.5 py-2 text-left transition-colors",
                  i === activeIndex ? "bg-hover" : "hover:bg-hover"
                )}
              >
                {iconFor(r.kind)}
                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs font-medium text-content">{r.title}</p>
                  <p className="truncate text-[11px] text-content-muted">{r.subtitle}</p>
                </div>
                <span className="text-[10px] uppercase tracking-wider text-content-muted">
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
