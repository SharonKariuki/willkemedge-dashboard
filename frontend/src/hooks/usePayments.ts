import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { ReceiptData, Transaction } from "@/lib/types";

export interface Payment {
  id: number;
  tenant: number;
  tenant_name: string;
  unit_label: string;
  building_name: string;
  amount: string;
  payment_date: string;
  period_month: number;
  period_year: number;
  source: string;
  source_display: string;
  payment_type: string;
  reference: string;
  transaction_id?: number;
  notes: string;
  is_void: boolean;
  voided_at: string | null;
  void_reason: string;
  created_at: string;
}


interface CollectionProgress {
  expected: string;
  collected: string;
  percentage: string;
  period_month: number;
  period_year: number;
}

interface PaymentFilters {
  tenant?: number | string;
  source?: string;
  period_month?: number;
  period_year?: number;
  /** "true" also returns voided rows, which the API hides by default. */
  include_void?: string;
}

export function usePayments(filters?: PaymentFilters) {
  return useQuery<Payment[]>({
    queryKey: ["payments", filters],
    queryFn: async () => {
      const { data } = await api.get("/payments/", { params: filters });
      return data;
    },
  });
}

export function useRecentPayments() {
  return useQuery<Payment[]>({
    queryKey: ["payments", "recent"],
    queryFn: async () => {
      const { data } = await api.get("/payments/recent/");
      return data;
    },
  });
}

export function useCollectionProgress(month?: number, year?: number) {
  const now = new Date();
  const m = month ?? now.getMonth() + 1;
  const y = year ?? now.getFullYear();
  return useQuery<CollectionProgress>({
    queryKey: ["payments", "collection-progress", m, y],
    queryFn: async () => {
      const { data } = await api.get("/payments/collection-progress/", {
        params: { month: m, year: y },
      });
      return data;
    },
  });
}

export function useCreatePayment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: Record<string, unknown>) => {
      const { data } = await api.post("/payments/", payload);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["payments"] });
      qc.invalidateQueries({ queryKey: ["units"] });
      qc.invalidateQueries({ queryKey: ["arrears"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      qc.invalidateQueries({ queryKey: ["reports"] });
    },
  });
}

export function useResendReceipt() {
  return useMutation({
    mutationFn: async (paymentId: number) => {
      const { data } = await api.post(`/payments/${paymentId}/resend-receipt/`);
      return data;
    },
  });
}

/**
 * What a void would actually unwind.
 *
 * One bank credit is often several Payment rows — FIFO allocation splits it
 * across the periods it settles — so the confirmation has to show the whole
 * group, not just the row that was clicked.
 */
export interface VoidPreview {
  payment: Payment;
  siblings: Payment[];
  total: string;
}

export function useVoidPreview(paymentId: number | null) {
  return useQuery<VoidPreview>({
    queryKey: ["payments", paymentId, "void-preview"],
    queryFn: async () => {
      const { data } = await api.get(`/payments/${paymentId}/void-preview/`);
      return data;
    },
    enabled: paymentId !== null,
    staleTime: 0,
  });
}

interface VoidPayload {
  id: number;
  reason: string;
  /** "reference" unwinds the whole credit; "single" just this row. */
  scope: "reference" | "single";
}

export function useVoidPayment() {
  const qc = useQueryClient();
  return useMutation<{ voided_count: number }, Error, VoidPayload>({
    mutationFn: async ({ id, reason, scope }) => {
      const { data } = await api.post(`/payments/${id}/void/`, { reason, scope });
      return data;
    },
    onSuccess: () => {
      // A void moves money back out of arrears and the ledger, so everything
      // derived from it is now stale.
      qc.invalidateQueries({ queryKey: ["payments"] });
      qc.invalidateQueries({ queryKey: ["units"] });
      qc.invalidateQueries({ queryKey: ["arrears"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      qc.invalidateQueries({ queryKey: ["reports"] });
      qc.invalidateQueries({ queryKey: ["tenants"] });
      qc.invalidateQueries({ queryKey: ["transactions"] });
    },
  });
}

interface MockPaymentPayload {
  tenant: number;
  amount: string | number;
  source: "mpesa" | "bank" | "cash";
}

export function useMockPayment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: MockPaymentPayload) => {
      const { data } = await api.post("/payments/mock/", payload);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["payments"] });
      qc.invalidateQueries({ queryKey: ["units"] });
      qc.invalidateQueries({ queryKey: ["arrears"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      qc.invalidateQueries({ queryKey: ["transactions"] });
    },
  });
}

// ---------------------------------------------------------------------------
// Transactions
// ---------------------------------------------------------------------------

interface TransactionFilters {
  tenant?: number | string;
  classification?: "RESIDENTIAL" | "BUSINESS";
}

export function useTransactions(filters?: TransactionFilters) {
  return useQuery<Transaction[]>({
    queryKey: ["transactions", filters],
    queryFn: async () => {
      const { data } = await api.get("/transactions/", { params: filters });
      return data;
    },
  });
}

export function useTransaction(id: number | string) {
  return useQuery<Transaction>({
    queryKey: ["transactions", id],
    queryFn: async () => {
      const { data } = await api.get(`/transactions/${id}/`);
      return data;
    },
    enabled: !!id,
  });
}

/**
 * Fetch receipt data for a transaction.
 * Uses stored values from the backend — never recalculates.
 */
export function useReceipt(transactionId: number | string) {
  return useQuery<ReceiptData>({
    queryKey: ["transactions", transactionId, "receipt"],
    queryFn: async () => {
      const { data } = await api.get(`/transactions/${transactionId}/receipt/`);
      return data;
    },
    enabled: !!transactionId,
  });
}
