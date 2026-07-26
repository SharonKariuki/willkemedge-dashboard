/**
 * Shared validators for money-entry form fields.
 *
 * Form amounts arrive as strings from text inputs. Validating only presence
 * (`z.string().min(1)`) lets non-numeric or negative values through to the API,
 * which returns a confusing 400 instead of inline field feedback. These helpers
 * give zod `.refine()` calls a single, tested source of truth.
 *
 * Note: `Number("12,000")` is `NaN`, so a thousands-separated value is rejected
 * — the user is nudged to enter a plain number the backend can parse.
 */

/** True when `v` parses to a number strictly greater than zero. */
export function isPositiveAmount(v: string): boolean {
  const n = Number(v);
  return Number.isFinite(n) && n > 0;
}

/** True when `v` is blank/absent, or parses to a number >= 0 (optional fields). */
export function isNonNegativeAmountOrBlank(v?: string | null): boolean {
  if (v == null || v === "") return true;
  const n = Number(v);
  return Number.isFinite(n) && n >= 0;
}
