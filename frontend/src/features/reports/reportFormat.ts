/** Formatting, column and search helpers shared by the report tabs. */
import { useMemo, useState, type ReactNode } from "react";

export const selectCls =
  "glass rounded-md px-3 py-2 text-sm text-ink-900 focus:outline-none min-w-0 max-w-[16rem]";

const wholeFmt = new Intl.NumberFormat("en-KE", { maximumFractionDigits: 0 });
const centsFmt = new Intl.NumberFormat("en-KE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** `KES 12,500` or `KES 12,500.50` — a negative (a credit) in brackets, as the statements print it. */
export function kes(value: unknown): string {
  const n = Math.round(Number(value ?? 0) * 100) / 100;
  if (!Number.isFinite(n)) return "—";
  const abs = Math.abs(n);
  const text = Number.isInteger(abs) ? wholeFmt.format(abs) : centsFmt.format(abs);
  return n < 0 ? `(KES ${text})` : `KES ${text}`;
}

export function monthName(month: number, style: "short" | "long" = "long") {
  return new Date(2000, month - 1).toLocaleString("en-GB", { month: style });
}

export function fmtDate(iso: string | null | undefined) {
  if (!iso) return "—";
  const d = new Date(`${iso}T00:00:00`);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

export interface Col<R> {
  label: string;
  /** Raw value — what the CSV gets and what search matches. */
  get: (row: R) => string | number | null | undefined;
  /** A money column: right-aligned, formatted as KES on screen and in the PDF. */
  money?: boolean;
  /** Right-align a plain number. */
  numeric?: boolean;
  /** Custom on-screen cell (the CSV still uses `get`). */
  render?: (row: R) => ReactNode;
}

export function display<R>(col: Col<R>, row: R): string {
  const v = col.get(row);
  if (v === null || v === undefined || v === "") return "—";
  return col.money ? kes(v) : String(v);
}

export const TENANT_STATUS_OPTIONS: [string, string][] = [
  ["all", "All tenants"],
  ["current", "Current tenants"],
  ["former", "Former tenants"],
];

/** Filter rows by free text across every column's raw value. */
export function useRowSearch<R>(rows: R[] | undefined, cols: Col<R>[]) {
  const [q, setQ] = useState("");
  const filtered = useMemo(() => {
    if (!rows) return rows;
    const needle = q.trim().toLowerCase();
    if (!needle) return rows;
    return rows.filter((r) =>
      cols.some((c) => String(c.get(r) ?? "").toLowerCase().includes(needle)),
    );
  }, [rows, cols, q]);
  return { q, setQ, rows: filtered };
}
