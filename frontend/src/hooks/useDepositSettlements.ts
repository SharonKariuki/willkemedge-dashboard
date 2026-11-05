/**
 * Deposit settlement at move-out — Settle Deposit, Mark Refund Sent, Void.
 *
 * A settlement is a numbered document on the backend (DS-…): the deposit held,
 * each deduction kept from it, and the refund. The unpaid-balance deduction is
 * a CR-… credit on the tenant's account, so every mutation refreshes the same
 * queries the credit screens do — the Balance card, Credit History, rent roll.
 */
import { useMutation, useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";

import { type Refund, useRefreshAccount } from "./useCredits";

export type DeductionKind = "unpaid_balance" | "damages" | "cleaning" | "other";
export type RefundBasis = "remainder" | "amount" | "percentage";

export interface DepositDeduction {
  id: number;
  kind: DeductionKind;
  kind_display: string;
  description: string;
  amount: string;
  expense_category: number | null;
  expense_category_name: string;
}

export interface DepositSettlement {
  id: number;
  number: string;
  tenant: number;
  settlement_date: string;
  deposit_held: string;
  balance_owed: string;
  deductions: DepositDeduction[];
  deductions_total: string;
  refund_basis: RefundBasis;
  refund_basis_display: string;
  refund_percentage: string | null;
  refund_amount: string;
  refund_status: "none" | "to_send" | "sent";
  refund_status_display: string;
  method: Refund["method"] | "";
  method_display: string;
  paid_to: string;
  reference: string;
  sent_on: string | null;
  notes: string;
  credit: number | null;
  credit_number: string;
  created_by_name: string;
  created_at: string;
  is_void: boolean;
  voided_at: string | null;
  void_reason: string;
}

export interface SettlementPreview {
  deposit_held: string;
  balance_owed: string;
  can_settle: boolean;
  tenant_status: string;
  tenant_phone: string;
  settlement: DepositSettlement | null;
  default_categories: Partial<Record<DeductionKind, number | null>>;
  expense_categories: { id: number; name: string }[];
}

export interface SettlePayload {
  tenant: number;
  settlement_date: string;
  deductions: { kind: DeductionKind; description: string; amount: string; expense_category: number | null }[];
  refund_basis: RefundBasis;
  refund_amount: string | null;
  refund_percentage: string | null;
  method: Refund["method"] | "";
  paid_to: string;
  reference: string;
  already_sent: boolean;
  sent_on: string | null;
  notes: string;
}

// Under "credits" so the credit screens' refresh reaches these too.
const keys = {
  preview: (tenantId: number | string) => ["credits", tenantId, "deposit-preview"] as const,
};

export function useSettlementPreview(tenantId: number | string | null) {
  return useQuery<SettlementPreview>({
    queryKey: keys.preview(tenantId ?? ""),
    queryFn: async () => {
      const { data } = await api.get("/deposit-settlements/preview/", { params: { tenant: tenantId } });
      return data;
    },
    enabled: !!tenantId,
  });
}

export function useSettleDeposit() {
  const refresh = useRefreshAccount();
  return useMutation({
    mutationFn: async (payload: SettlePayload) => {
      const { data } = await api.post("/deposit-settlements/", payload);
      return data as DepositSettlement;
    },
    onSuccess: refresh,
  });
}

export function useMarkDepositRefundSent() {
  const refresh = useRefreshAccount();
  return useMutation({
    mutationFn: async ({ id, ...body }: {
      id: number; sent_on: string; method: Refund["method"]; reference: string; paid_to?: string;
    }) => {
      const { data } = await api.post(`/deposit-settlements/${id}/mark-sent/`, body);
      return data as DepositSettlement;
    },
    onSuccess: refresh,
  });
}

export function useVoidDepositSettlement() {
  const refresh = useRefreshAccount();
  return useMutation({
    mutationFn: async ({ id, reason }: { id: number; reason: string }) => {
      const { data } = await api.post(`/deposit-settlements/${id}/void/`, { reason });
      return data as DepositSettlement;
    },
    onSuccess: refresh,
  });
}
