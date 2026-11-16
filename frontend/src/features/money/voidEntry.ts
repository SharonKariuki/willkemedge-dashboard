import toast from "react-hot-toast";

import { getErrorMessage } from "@/lib/apiError";

/**
 * Ask why, then void. Voided entries stay on the list, struck through, with
 * who voided them and why; they drop out of totals and the books.
 */
export function askAndVoid(
  noun: string,
  run: (reason: string) => Promise<unknown>,
): void {
  const reason = window.prompt(
    `Void this ${noun}? It stays on the list, struck through, and leaves the totals and the books.\n\nWhy is it being voided?`,
  );
  if (reason === null) return;
  if (!reason.trim()) {
    toast.error("Say why it is being voided.");
    return;
  }
  run(reason.trim()).then(
    () => toast.success(`The ${noun} is void.`),
    (err) => toast.error(getErrorMessage(err)),
  );
}

/** Totals count live entries only. */
export function liveTotal(rows: { amount: string; is_void?: boolean }[] | undefined): number {
  return (rows ?? []).reduce((sum, r) => (r.is_void ? sum : sum + parseFloat(r.amount)), 0);
}
