/**
 * Values the credit screens share.
 *
 * The words on those screens are a property manager's, not an accountant's:
 * "Add Credit", "Credit on Account", "Apply to Next Invoice", "Refund Credit".
 * The accounting behind each choice — which account a credit is charged to, the
 * VAT that comes back on a credit note — is decided on the server from the
 * reason chosen, and the screens only describe the effect on the tenant.
 */
import type { Refund } from "@/hooks/useCredits";
import { formatKES } from "@/lib/money";

export const KES = formatKES;
export const round2 = (n: number) => Math.round(n * 100) / 100;

export const METHODS: { value: Refund["method"]; label: string }[] = [
  { value: "mpesa", label: "M-Pesa" },
  { value: "bank", label: "Bank transfer" },
  { value: "cash", label: "Cash" },
  { value: "cheque", label: "Cheque" },
];

/** Methods that leave a trace on a statement, so the reference is required. */
export const NEEDS_REFERENCE = new Set<Refund["method"]>(["mpesa", "bank", "cheque"]);
