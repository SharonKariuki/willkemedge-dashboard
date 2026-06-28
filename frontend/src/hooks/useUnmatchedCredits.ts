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

/** Assign an unmatched credit to a tenant — books the payment server-side. */
export function useAssignCredit() {
  const qc = useQueryClient();
  return useMutation<AssignCreditResult, Error, { id: number; tenant: number }>({
    mutationFn: async ({ id, tenant }) => {
      const { data } = await api.post(`/unmatched-credits/${id}/assign/`, { tenant });
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
