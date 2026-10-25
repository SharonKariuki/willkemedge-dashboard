import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

export interface UnmatchedCredit {
  id: number;
  transaction_id: string;
  payment_ref: string;
  account_number: string;
  amount: string;
  channel: string;
  narration: string;
  detail: string;
  status: string;
  received_at: string;
  payer_hint: { phone: string; name: string };
  /** Times this credit was voided and sent back here; non-zero = returned from a void. */
  void_requeue_count: number;
}

export interface AssignCreditResult {
  detail: string;
  payment_id: number | null;
}

/** Co-op credits that couldn't be auto-matched — the reconciliation queue. */
export function useUnmatchedCredits() {
  return useQuery<UnmatchedCredit[]>({
    queryKey: ["unmatched-credits"],
    queryFn: async () => {
      const { data } = await api.get("/unmatched-credits/");
      return data;
    },
  });
}

/** How assign would divide a credit by default — deposit first for a new letting. */
export interface CreditSplit {
  amount: string;
  deposit_amount: string;
  rent_amount: string;
  /** The deposit on the tenant's card the books have not received yet. */
  deposit_still_to_receive: string;
}

export function useCreditSplit(id: number, tenant: number | null) {
  return useQuery<CreditSplit>({
    queryKey: ["unmatched-credits", id, "split", tenant],
    queryFn: async () => {
      const { data } = await api.get(`/unmatched-credits/${id}/split/`, { params: { tenant } });
      return data;
    },
    enabled: tenant !== null,
  });
}

/** Assign an unmatched credit to a tenant — books the payment server-side.
 *  `deposit_amount` is the part booked as deposit; the rest is rent. */
export function useAssignCredit() {
  const qc = useQueryClient();
  return useMutation<
    AssignCreditResult, Error, { id: number; tenant: number; deposit_amount?: string }
  >({
    mutationFn: async ({ id, tenant, deposit_amount }) => {
      const { data } = await api.post(`/unmatched-credits/${id}/assign/`, {
        tenant,
        ...(deposit_amount !== undefined ? { deposit_amount } : {}),
      });
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["unmatched-credits"] });
      qc.invalidateQueries({ queryKey: ["payments"] });
      qc.invalidateQueries({ queryKey: ["tenants"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}
