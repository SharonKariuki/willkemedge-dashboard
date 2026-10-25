/**
 * "First rent month" — the first month a letting is charged rent for.
 *
 * Blank means the move-in month, which is billed in full. Someone who gets the
 * keys on 31 October and starts paying in November needs November here, or the
 * rent run charges October (MR203). The API stores the 1st of the month; the
 * form works in the browser's "YYYY-MM" month value.
 */
const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

/** From this day of the month on, the form suggests starting rent next month. */
export const LATE_MOVE_IN_DAY = 20;

/** "2026-11" → "November 2026". */
export function monthLabel(month: string): string {
  const [year, m] = month.split("-").map(Number);
  return m ? `${MONTHS[m - 1]} ${year}` : month;
}

/** "2026-11" → "2026-11-01", blank → null, for the API. */
export function firstRentMonthForApi(month: string | undefined): string | null {
  return month ? `${month}-01` : null;
}

/** "2026-11-01" from the API → "2026-11" for the month input. */
export function firstRentMonthFromApi(value: string | null | undefined): string {
  return value ? value.slice(0, 7) : "";
}

/** The month after a "YYYY-MM-DD" move-in, as "YYYY-MM". */
export function monthAfter(moveIn: string): string {
  const [year, month] = moveIn.split("-").map(Number);
  return month === 12 ? `${year + 1}-01` : `${year}-${String(month + 1).padStart(2, "0")}`;
}
