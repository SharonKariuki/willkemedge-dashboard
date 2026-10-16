/**
 * dates.ts — day/month/year, the way Kenya writes a date.
 *
 * Every date the API stores and returns is ISO `YYYY-MM-DD`, and it stays that
 * way: it sorts as a string, it compares as a string, and it is the one format
 * that cannot be read two ways. These helpers are the boundary between that
 * and what a person reads and types, which here is always `dd/mm/yyyy`.
 *
 * The native `<input type="date">` is not that boundary, which is what caused
 * the bug this file exists for. It renders in the *browser's* locale, so on a
 * machine set to en-US the landlord was shown `mm/dd/yyyy` and had no way to
 * enter 1 October except as `10/01/2026`. See `components/ui/DatePicker`.
 */

/** `2026-10-01` → `01/10/2026`. Anything that isn't a plain ISO date → `""`. */
export function toDayFirst(iso: string | null | undefined): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso ?? "").trim());
  if (!match) return "";
  const [, year, month, day] = match;
  return `${day}/${month}/${year}`;
}

/** True when y-m-d name a real calendar day — rejects 31/02, 31/04, 29/02/2027. */
function isRealDate(year: number, month: number, day: number): boolean {
  if (month < 1 || month > 12 || day < 1 || day > 31) return false;
  // Date rolls 31 February forward into March; a round-trip catches that.
  const d = new Date(Date.UTC(year, month - 1, day));
  return (
    d.getUTCFullYear() === year && d.getUTCMonth() === month - 1 && d.getUTCDate() === day
  );
}

const pad = (n: string) => n.padStart(2, "0");

/**
 * What a person typed → ISO, or `""` when it isn't yet a complete, real date.
 *
 * Day-first throughout. Separators are whatever came to hand (`/ - .` or
 * none), because someone copying a date off a lease types what they see.
 * A bare ISO string passes through untouched so a pasted `2026-10-01`, and
 * the values react-hook-form seeds from `defaultValues`, both still work.
 *
 * The year must be all four digits. `01/10/20` is not 2020 here — it is
 * someone two keystrokes into `01/10/2026`, and a system that bills from these
 * dates should not have to guess which. Requiring four removes the question.
 *
 * A half-typed date is `""` rather than an error: it is not wrong yet, it is
 * unfinished, and the field should not go red while someone is still typing.
 */
export function fromDayFirst(text: string | null | undefined): string {
  const raw = String(text ?? "").trim();
  if (!raw) return "";

  // ISO, as pasted or as seeded by the form.
  const iso = /^(\d{4})-(\d{2})-(\d{2})$/.exec(raw);
  if (iso) {
    const [, y, m, d] = iso;
    return isRealDate(+y, +m, +d) ? raw : "";
  }

  const parts = /^(\d{1,2})[/\-. ](\d{1,2})[/\-. ](\d{4})$/.exec(raw)
    ?? /^(\d{2})(\d{2})(\d{4})$/.exec(raw);
  if (!parts) return "";

  const [, day, month, year] = parts;
  if (!isRealDate(+year, +month, +day)) return "";
  return `${year}-${pad(month)}-${pad(day)}`;
}

/**
 * Tidy what is in the box as it is typed: `01102026` → `01/10/2026`.
 *
 * Slashes are inserted only once there are digits past them, so backspacing
 * through one deletes it rather than having it reappear under the cursor.
 * A string that is on its way to being ISO is left alone — masking a pasted
 * `2026-10-01` into `20/26/1001` would be worse than doing nothing.
 */
export function maskDayFirst(raw: string): string {
  if (/^\d{4}-\d{0,2}-?\d{0,2}$/.test(raw)) return raw;

  const digits = raw.replace(/\D/g, "").slice(0, 8);
  if (digits.length <= 2) return digits;
  if (digits.length <= 4) return `${digits.slice(0, 2)}/${digits.slice(2)}`;
  return `${digits.slice(0, 2)}/${digits.slice(2, 4)}/${digits.slice(4)}`;
}

/** Today, as ISO — the default a form seeds a date field with. */
export function todayIso(): string {
  const now = new Date();
  return `${now.getFullYear()}-${pad(String(now.getMonth() + 1))}-${pad(String(now.getDate()))}`;
}
