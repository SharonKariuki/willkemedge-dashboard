/**
 * Tenant credits and refunds — Add Credit, Credit on Account, Refund Credit.
 *
 * A credit is a numbered document on the backend (CN-… for a credit note that
 * corrects a charge, CR-… for any other credit, RF-… for a refund); the balance
 * is always derived from them. Every mutation here refreshes the tenant, the
 * payment history (rent roll) and the credit position together, so the
 * Balance card, the Credits panel and the rent roll never disagree on screen.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

export type CreditReasonValue =
  | "billing_correction"
  | "rent_concession"
  | "tenant_paid_cost"
  | "opening_credit";

export interface CreditReasonOption {
  value: CreditReasonValue;
  label: string;
  /** "credit_note" corrects a charge (and its VAT); "account_credit" does not. */
  document: "credit_note" | "account_credit";
  needs_charge: boolean;
  rent_only: boolean;
  needs_category: boolean;
}

export interface CreditableCharge {
  id: number;
  label: string;
  charged: string;
  vat: string | number;
  /** How much of the charge (before VAT) can still be credited. */
  creditable: string;
  /** VAT as a fraction of the charge's rent — "0.1600" for a VAT-rated shop. */
  vat_rate: string;
}

export interface CreditPosition {
  /** The balance the rest of the product reports — negative = in credit. */
  balance: string;
  credit_on_account: string;
  overpayment_credit: string;
  credits_available: string;
  credits_held: string;
  refunds_to_send: string;
  refundable: string;
  reasons: CreditReasonOption[];
  rent_charges: CreditableCharge[];
  water_charges: CreditableCharge[];
  expense_categories: { id: number; name: string }[];
  tenant_phone: string;
}

export interface CreditHistoryEvent {
  at: string;
  date: string;
  kind: "issued" | "applied" | "unapplied" | "refund" | "void";
  text: string;
  amount: string;
}

export interface TenantCredit {
  id: number;
  number: string;
  tenant: number;
  credit_type: "credit_note" | "account_credit";
  credit_type_display: string;
  reason: CreditReasonValue;
  reason_display: string;
  credit_date: string;
  net_amount: string;
  vat_amount: string;
  amount: string;
  amount_applied: string;
  amount_refunded: string;
  remaining: string;
  status: "issued" | "void";
  status_display: "Available" | "Held" | "Partly used" | "Fully used" | "Void";
  is_void: boolean;
  on_hold: boolean;
  description: string;
  internal_notes: string;
  reference: string;
  has_evidence: boolean;
  evidence_name: string;
  corrects: string;
  expense_category_name: string;
  created_by_name: string;
  created_at: string;
  approved_by_name: string;
  approval_mode: string;
  voided_at: string | null;
  voided_by_name: string;
  void_reason: string;
  history: CreditHistoryEvent[];
}

export interface Refund {
  id: number;
  number: string;
  tenant: number;
  amount: string;
  method: "mpesa" | "bank" | "cash" | "cheque";
  method_display: string;
  paid_to: string;
  reference: string;
  notes: string;
  status: "scheduled" | "sent" | "cancelled" | "void";
  status_display: string;
  sent_on: string | null;
  lines: { source: string; amount: string }[];
  created_by_name: string;
  created_at: string;
  sent_recorded_by_name: string;
  closed_by_name: string;
  close_reason: string;
}

export interface VoidCreditPreview {
  reopened: { label: string; amount: string }[];
  reopened_total: string;
  refunded_kept: string;
  refunds_cancelled: string;
  tenant_will_owe_more_by: string;
}

const keys = {
  position: (tenantId: number | string) => ["credits", tenantId, "position"] as const,
  credits: (tenantId: number | string) => ["credits", tenantId, "list"] as const,
  refunds: (tenantId: number | string) => ["credits", tenantId, "refunds"] as const,
};

export function useCreditPosition(tenantId: number | string | null) {
  return useQuery<CreditPosition>({
    queryKey: keys.position(tenantId ?? ""),
    queryFn: async () => {
      const { data } = await api.get("/tenant-credits/position/", { params: { tenant: tenantId } });
      return data;
    },
    enabled: !!tenantId,
  });
}

export function useTenantCredits(tenantId: number | string | null) {
  return useQuery<TenantCredit[]>({
    queryKey: keys.credits(tenantId ?? ""),
    queryFn: async () => {
      const { data } = await api.get("/tenant-credits/", { params: { tenant: tenantId } });
      return data;
    },
    enabled: !!tenantId,
  });
}

export function useTenantRefunds(tenantId: number | string | null) {
  return useQuery<Refund[]>({
    queryKey: keys.refunds(tenantId ?? ""),
    queryFn: async () => {
      const { data } = await api.get("/refunds/", { params: { tenant: tenantId } });
      return data;
    },
    enabled: !!tenantId,
  });
}

export function useVoidCreditPreview(creditId: number | null) {
  return useQuery<VoidCreditPreview>({
    queryKey: ["credits", "void-preview", creditId],
    queryFn: async () => {
      const { data } = await api.get(`/tenant-credits/${creditId}/void-preview/`);
      return data;
    },
    enabled: creditId != null,
    // Always fresh: it states what the void will do right now.
    staleTime: 0,
  });
}

/** Everything a credit or refund changes, refreshed together. The "tenants"
 *  prefix covers the tenant, its payment history (rent roll) and the list. */
function useRefreshAccount() {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: ["credits"] });
    qc.invalidateQueries({ queryKey: ["tenants"] });
    qc.invalidateQueries({ queryKey: ["dashboard"] });
  };
}

export function useAddCredit() {
  const refresh = useRefreshAccount();
  return useMutation({
    mutationFn: async (form: FormData) => {
      const { data } = await api.post("/tenant-credits/", form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      return data as TenantCredit;
    },
    onSuccess: refresh,
  });
}

export function useHoldCredit() {
  const refresh = useRefreshAccount();
  return useMutation({
    mutationFn: async ({ id, hold }: { id: number; hold: boolean }) => {
      const { data } = await api.post(`/tenant-credits/${id}/hold/`, { hold });
      return data as TenantCredit;
    },
    onSuccess: refresh,
  });
}

export function useVoidCredit() {
  const refresh = useRefreshAccount();
  return useMutation({
    mutationFn: async ({ id, reason }: { id: number; reason: string }) => {
      const { data } = await api.post(`/tenant-credits/${id}/void/`, { reason });
      return data as TenantCredit;
    },
    onSuccess: refresh,
  });
}

export interface RefundPayload {
  tenant: number;
  amount: string;
  method: Refund["method"];
  paid_to: string;
  reference: string;
  notes: string;
  already_sent: boolean;
  sent_on: string | null;
  credit: number | null;
}

export function useCreateRefund() {
  const refresh = useRefreshAccount();
  return useMutation({
    mutationFn: async (payload: RefundPayload) => {
      const { data } = await api.post("/refunds/", payload);
      return data as Refund;
    },
    onSuccess: refresh,
  });
}

export function useMarkRefundSent() {
  const refresh = useRefreshAccount();
  return useMutation({
    mutationFn: async ({ id, ...body }: {
      id: number; sent_on: string; reference: string; method?: Refund["method"]; paid_to?: string;
    }) => {
      const { data } = await api.post(`/refunds/${id}/mark-sent/`, body);
      return data as Refund;
    },
    onSuccess: refresh,
  });
}

export function useCloseRefund() {
  const refresh = useRefreshAccount();
  return useMutation({
    mutationFn: async ({ id, action, reason }: { id: number; action: "cancel" | "void"; reason: string }) => {
      const { data } = await api.post(`/refunds/${id}/${action}/`, { reason });
      return data as Refund;
    },
    onSuccess: refresh,
  });
}
