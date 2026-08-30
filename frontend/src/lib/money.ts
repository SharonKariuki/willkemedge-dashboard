/**
 * Shared money formatting.
 *
 * `formatBalance` is the one place a rent-roll balance becomes text. The
 * balance can legitimately go negative — a tenant in credit — and every page
 * that shows it (tenant list, tenant detail, building drill-down, dashboard,
 * reports) is expected to render that the same way: "X cr" rather than a bare
 * "-X", which reads as an error rather than money in hand. Duplicating this
 * per-page is how one page quietly drifts from the rest.
 */

/** "KES 20,000" — a plain money amount with a currency prefix. */
export function formatKES(value: string | number | null | undefined): string {
  return `KES ${Number(value || 0).toLocaleString()}`;
}

/**
 * "20,000" in arrears (owed), "20,000 cr" in credit, "0" when square.
 * No currency prefix — callers that want one wrap the result themselves.
 */
export function formatBalance(value: string | number | null | undefined): string {
  const amount = Number(value || 0);
  if (amount < 0) {
    return `${Math.abs(amount).toLocaleString()} cr`;
  }
  return amount.toLocaleString();
}

/** Same as `formatBalance` but with the "KES" prefix, for summary/KPI cards. */
export function formatBalanceKES(value: string | number | null | undefined): string {
  return `KES ${formatBalance(value)}`;
}

/** Tailwind tone class: "owed" when the balance is positive, "clear" when square or in credit. */
export function balanceTone(value: string | number | null | undefined): "owed" | "clear" {
  return Number(value || 0) > 0 ? "owed" : "clear";
}
