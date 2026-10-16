/**
 * rentRollFilter.ts — which months of a tenant's rent roll to show.
 *
 * The roll is a running balance: each row's arrears b/f is the previous row's
 * balance. So a filter only ever hides rows; it never re-derives a figure. The
 * first visible row still opens on the true b/f, which is the whole history
 * before it in one number.
 *
 * A filter is one string so it can sit in the URL (`?roll=`):
 *   "1m" | "3m" | "12m" — the last N calendar months up to and including this one
 *   "all"               — every row
 *   "YYYY-MM"           — that one month
 * Anything else falls back to the default, the last three months.
 */

export type RentRollFilter = string;

export const DEFAULT_RENT_ROLL_FILTER: RentRollFilter = "3m";

export const RENT_ROLL_PRESETS: { value: RentRollFilter; label: string }[] = [
  { value: "1m", label: "Past month" },
  { value: "3m", label: "Past 3 months" },
  { value: "12m", label: "Past year" },
  { value: "all", label: "All months" },
];

const PRESET_MONTHS: Record<string, number> = { "1m": 1, "3m": 3, "12m": 12 };
const MONTH_RE = /^(\d{4})-(0[1-9]|1[0-2])$/;

interface RollRow {
  period_month: number;
  period_year: number;
}

const monthKey = (year: number, month: number) => year * 12 + (month - 1);

/** `2026-08` for a row, the value a single-month filter carries. */
export function rowMonthValue(row: RollRow): string {
  return `${row.period_year}-${String(row.period_month).padStart(2, "0")}`;
}

/** A filter read off the URL → one this module understands, else the default. */
export function parseRentRollFilter(raw: string | null | undefined): RentRollFilter {
  const value = String(raw ?? "").trim();
  if (value === "all" || value in PRESET_MONTHS || MONTH_RE.test(value)) return value;
  return DEFAULT_RENT_ROLL_FILTER;
}

/**
 * The rows `filter` keeps, in their original order.
 *
 * A preset window ends at the current month but does not cut off rows after
 * it: a tenant who has paid ahead has rows past today, and those are the
 * newest thing on the roll, not history to hide.
 */
export function filterRentRoll<T extends RollRow>(
  rows: T[],
  filter: RentRollFilter,
  today: Date = new Date(),
): T[] {
  if (filter === "all") return rows;
  if (MONTH_RE.test(filter)) return rows.filter((r) => rowMonthValue(r) === filter);
  const months = PRESET_MONTHS[filter] ?? PRESET_MONTHS[DEFAULT_RENT_ROLL_FILTER];
  const from = monthKey(today.getFullYear(), today.getMonth() + 1) - (months - 1);
  return rows.filter((r) => monthKey(r.period_year, r.period_month) >= from);
}
