/**
 * Building blocks every report tab shares: filters, the live/refresh line,
 * a table that knows its columns (so screen, CSV and PDF print the same
 * thing), and the export buttons.
 */
import { Download, FileSpreadsheet, FileText, Loader2, RefreshCw, Search } from "lucide-react";
import { useState, type ReactNode } from "react";
import toast from "react-hot-toast";

import {
  Button, EmptyState, ErrorState, Skeleton,
  Table, TBody, TD, TH, THead, TR,
} from "@/components/ui";
import { useBuildings } from "@/hooks/useBuildings";
import { cn } from "@/lib/cn";
import { downloadFile, type ExportFormat } from "@/lib/downloadPdf";

import { display, kes, monthName, selectCls, type Col } from "./reportFormat";

// ─── export ──────────────────────────────────────────────────────────────────
export interface ExportSpec<R> {
  title: string;
  subtitle?: string;
  filename: string;
  cols: Col<R>[];
  rows: R[];
  /** A totals row, keyed by column label. */
  footer?: Record<string, string | number>;
}

/** CSV / Excel / PDF buttons. Each calls `onDownload(format)` and shows progress and errors. */
export function DownloadButtons({ onDownload, disabled }: {
  onDownload: (format: ExportFormat) => Promise<void>;
  disabled?: boolean;
}) {
  const [busy, setBusy] = useState<ExportFormat | null>(null);
  const run = async (format: ExportFormat) => {
    setBusy(format);
    try {
      await onDownload(format);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "The download failed.");
    } finally {
      setBusy(null);
    }
  };
  const button = (format: ExportFormat, label: string, Icon: typeof Download) => (
    <Button variant="glass" size="sm" disabled={disabled || busy !== null} onClick={() => void run(format)}
      title={`Download as ${label}`}>
      {busy === format ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Icon className="h-3.5 w-3.5" />}
      {label}
    </Button>
  );
  return (
    <div className="flex flex-wrap gap-2">
      {button("csv", "CSV", Download)}
      {button("xlsx", "Excel", FileSpreadsheet)}
      {button("pdf", "PDF", FileText)}
    </div>
  );
}

/** The table on screen, filters applied, as the server's export body. */
function exportBody<R>({ title, subtitle, filename, cols, rows, footer }: ExportSpec<R>, format: ExportFormat) {
  const columns = cols.map((c, i) => ({
    key: `c${i}`, label: c.label, kind: c.money ? "money" : c.numeric ? "number" : "text",
  }));
  const cell = (c: Col<R>, value: unknown) =>
    value === null || value === undefined ? "" : c.numeric && typeof value === "string" ? value : value;
  return {
    format, title, filename,
    subtitle: subtitle ? [subtitle] : [],
    columns,
    rows: rows.map((r) => Object.fromEntries(cols.map((c, i) => [`c${i}`, cell(c, c.get(r))]))),
    footer: footer ? Object.fromEntries(cols.map((c, i) => [`c${i}`, footer[c.label] ?? ""])) : undefined,
  };
}

export function ExportBar<R>(spec: ExportSpec<R>) {
  return (
    <DownloadButtons
      disabled={spec.rows.length === 0}
      onDownload={(format) => downloadFile("/reports/export/", {
        body: exportBody(spec, format), fallback: spec.filename,
      })}
    />
  );
}

// ─── table ───────────────────────────────────────────────────────────────────
export function ReportTable<R>({
  cols, rows, footer, isLoading, isError, onRetry, empty = "Nothing to show for these filters.",
  rowKey,
}: {
  cols: Col<R>[];
  rows: R[] | undefined;
  footer?: Record<string, string | number>;
  isLoading?: boolean;
  isError?: boolean;
  onRetry?: () => void;
  empty?: string;
  rowKey?: (row: R, index: number) => string | number;
}) {
  if (isLoading && !rows) return <Skeleton className="h-48" />;
  if (isError && !rows)
    return (
      <ErrorState
        title="This report could not be loaded."
        description="The figures did not come back. This is usually temporary."
        onRetry={onRetry}
      />
    );
  if (!rows || rows.length === 0) return <EmptyState title="No data" description={empty} />;
  const right = (c: Col<R>) => (c.money || c.numeric ? "text-right tabular-nums" : "");
  return (
    <Table minWidth={Math.max(cols.length * 130, 480)}>
      <THead>
        <TR>{cols.map((c) => <TH key={c.label} className={right(c)}>{c.label}</TH>)}</TR>
      </THead>
      <TBody>
        {rows.map((row, i) => (
          <TR key={rowKey ? rowKey(row, i) : i}>
            {cols.map((c) => (
              <TD key={c.label} className={right(c)}>{c.render ? c.render(row) : display(c, row)}</TD>
            ))}
          </TR>
        ))}
        {footer && (
          <TR className="border-t-2 border-ink-300">
            {cols.map((c) => {
              const v = footer[c.label];
              return (
                <TD key={c.label} className={cn("font-semibold text-ink-900", right(c))}>
                  {v === undefined ? "" : c.money && typeof v === "number" ? kes(v) : v}
                </TD>
              );
            })}
          </TR>
        )}
      </TBody>
    </Table>
  );
}

// ─── search ──────────────────────────────────────────────────────────────────
export function SearchBox({ value, onChange, placeholder = "Search tenant or unit…" }: {
  value: string; onChange: (v: string) => void; placeholder?: string;
}) {
  return (
    <label className="glass flex min-w-0 items-center gap-2 rounded-md px-3 py-2 text-sm">
      <Search className="h-3.5 w-3.5 shrink-0 text-ink-500" />
      <input
        type="search"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        aria-label={placeholder}
        className="w-40 min-w-0 bg-transparent text-ink-900 placeholder:text-ink-500 focus:outline-none sm:w-52"
      />
    </label>
  );
}

// ─── filters ─────────────────────────────────────────────────────────────────
export function FilterBar({ children }: { children: ReactNode }) {
  return <div className="flex min-w-0 flex-wrap items-center gap-2">{children}</div>;
}

export function BuildingFilter({ value, onChange, lettableOnly = false }: {
  value: number | null; onChange: (v: number | null) => void; lettableOnly?: boolean;
}) {
  const { data: buildings } = useBuildings();
  const list = (buildings ?? []).filter(
    (b) => !lettableOnly || !b.property_type || b.property_type === "rental",
  );
  return (
    <select
      aria-label="Building"
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
      className={selectCls}
    >
      <option value="">All buildings</option>
      {list.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
    </select>
  );
}

export function SelectFilter<T extends string>({ label, value, onChange, options }: {
  label: string; value: T; onChange: (v: T) => void; options: [T, string][];
}) {
  return (
    <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value as T)} className={selectCls}>
      {options.map(([v, text]) => <option key={v} value={v}>{text}</option>)}
    </select>
  );
}

const THIS_YEAR = new Date().getFullYear();
const YEARS = Array.from({ length: 7 }, (_, i) => THIS_YEAR + 1 - i);

export function YearPicker({ year, onYear }: { year: number; onYear: (y: number) => void }) {
  const years = YEARS.includes(year) ? YEARS : [...YEARS, year].sort((a, b) => b - a);
  return (
    <select aria-label="Year" value={year} onChange={(e) => onYear(Number(e.target.value))} className={selectCls}>
      {years.map((y) => <option key={y} value={y}>{y}</option>)}
    </select>
  );
}

export function MonthYearPicker({ month, year, onMonth, onYear }: {
  month: number; year: number; onMonth: (m: number) => void; onYear: (y: number) => void;
}) {
  const step = (delta: number) => {
    const k = year * 12 + (month - 1) + delta;
    onYear(Math.floor(k / 12));
    onMonth((k % 12) + 1);
  };
  return (
    <div className="flex items-center gap-1">
      <button type="button" aria-label="Previous month" onClick={() => step(-1)}
        className="glass rounded-md px-2 py-2 text-sm text-ink-600 hover:text-ink-900">‹</button>
      <select aria-label="Month" value={month} onChange={(e) => onMonth(Number(e.target.value))} className={selectCls}>
        {Array.from({ length: 12 }, (_, i) => (
          <option key={i + 1} value={i + 1}>{monthName(i + 1, "short")}</option>
        ))}
      </select>
      <YearPicker year={year} onYear={onYear} />
      <button type="button" aria-label="Next month" onClick={() => step(1)}
        className="glass rounded-md px-2 py-2 text-sm text-ink-600 hover:text-ink-900">›</button>
    </div>
  );
}

/** `YYYY-MM` month range; blank ends are open. */
export function MonthRange({ from, to, onFrom, onTo }: {
  from: string; to: string; onFrom: (v: string) => void; onTo: (v: string) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-1 text-xs text-ink-500">
      <span>From</span>
      <input type="month" aria-label="From month" value={from} onChange={(e) => onFrom(e.target.value)} className={selectCls} />
      <span>to</span>
      <input type="month" aria-label="To month" value={to} onChange={(e) => onTo(e.target.value)} className={selectCls} />
    </div>
  );
}

export function DateRange({ from, to, onFrom, onTo }: {
  from: string; to: string; onFrom: (v: string) => void; onTo: (v: string) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-1 text-xs text-ink-500">
      <span>From</span>
      <input type="date" aria-label="From date" value={from} onChange={(e) => onFrom(e.target.value)} className={selectCls} />
      <span>to</span>
      <input type="date" aria-label="To date" value={to} onChange={(e) => onTo(e.target.value)} className={selectCls} />
    </div>
  );
}

// ─── live status ─────────────────────────────────────────────────────────────
/** "Updated 14:32 · Refresh" — says how fresh the figures are and fetches again. */
export function LiveStatus({ query }: {
  query: { dataUpdatedAt: number; isFetching: boolean; refetch: () => unknown };
}) {
  const when = query.dataUpdatedAt
    ? new Date(query.dataUpdatedAt).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" })
    : null;
  return (
    <button
      type="button"
      onClick={() => void query.refetch()}
      className="inline-flex items-center gap-1.5 text-xs text-ink-500 hover:text-ink-900"
      title="Fetch the latest figures"
    >
      <RefreshCw className={cn("h-3.5 w-3.5", query.isFetching && "animate-spin")} />
      {query.isFetching ? "Updating…" : when ? `Updated ${when}` : "Refresh"}
    </button>
  );
}

export function SummaryCard({ label, value, tone = "ink", hint }: {
  label: string; value: string; tone?: "sage" | "coral" | "peri" | "ochre" | "ink"; hint?: string;
}) {
  const toneClass = {
    sage: "text-sage-700 dark:text-sage-400",
    coral: "text-status-unpaid",
    peri: "text-peri-600 dark:text-peri-400",
    ochre: "text-ochre-600",
    ink: "text-ink-900",
  }[tone];
  return (
    <div className="neu-sm min-w-0 p-4">
      <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">{label}</p>
      <p className={cn("mt-1 truncate font-display text-xl font-semibold", toneClass)}>{value}</p>
      {hint && <p className="mt-0.5 text-xs text-ink-500">{hint}</p>}
    </div>
  );
}
