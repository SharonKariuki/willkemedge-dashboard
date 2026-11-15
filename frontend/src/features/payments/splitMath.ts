/**
 * Allocation arithmetic for a payment split across tenancies.
 *
 * Money is compared in whole cents so 0.1 + 0.2 never fails to add up to a
 * cheque. The API checks the same rule; this is what lets the form say how
 * much is left to allocate before anything is sent.
 */

export interface SplitRow {
  key: string;
  tenant: number | null;
  amount: string;
  period_month: number;
  period_year: number;
}

/** "12,500.50" -> 1250050; blank or not a number -> null. */
export function toCents(value: string): number | null {
  const cleaned = value.replace(/,/g, "").trim();
  if (!cleaned) return null;
  const n = Number(cleaned);
  return Number.isFinite(n) ? Math.round(n * 100) : null;
}

export function centsToAmount(cents: number): string {
  return (cents / 100).toFixed(2);
}

export interface Allocation {
  totalCents: number;
  allocatedCents: number;
  /** Positive: still to allocate. Negative: allocated more than was received. */
  remainingCents: number;
  /** Why the split can't be saved yet; empty when it can. */
  problems: string[];
}

export function allocate(total: string, rows: SplitRow[]): Allocation {
  const totalCents = toCents(total) ?? 0;
  const allocatedCents = rows.reduce((sum, r) => sum + Math.max(toCents(r.amount) ?? 0, 0), 0);
  const remainingCents = totalCents - allocatedCents;

  const problems: string[] = [];
  if (totalCents <= 0) problems.push("Enter the amount received.");
  if (rows.length < 2) problems.push("Split across at least two tenancies.");
  if (rows.some((r) => !r.tenant)) problems.push("Choose a tenancy for every part.");
  if (rows.some((r) => (toCents(r.amount) ?? 0) <= 0)) problems.push("Every part needs an amount.");
  if (totalCents > 0 && remainingCents !== 0) {
    problems.push(
      remainingCents > 0
        ? `KES ${centsToAmount(remainingCents)} still to allocate.`
        : `Allocated KES ${centsToAmount(-remainingCents)} more than was received.`,
    );
  }
  return { totalCents, allocatedCents, remainingCents, problems };
}

let seq = 0;
export function newRow(period_month: number, period_year: number): SplitRow {
  seq += 1;
  return { key: `part-${seq}`, tenant: null, amount: "", period_month, period_year };
}
