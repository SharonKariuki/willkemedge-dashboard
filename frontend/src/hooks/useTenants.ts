import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { TenantDetail, TenantListItem } from "@/lib/types";

export interface TenantFilters {
  status?: string;
  kyc_status?: string;
  building?: number | string;
  unit?: number | string;
  search?: string;
  payment_status?: string;
}

export function useTenants(filters?: TenantFilters) {
  return useQuery<TenantListItem[]>({
    queryKey: ["tenants", filters],
    queryFn: async () => {
      const { data } = await api.get("/tenants/", { params: filters });
      return data;
    },
  });
}

/** One month of the rent roll: b/f + rent + VAT + other charges - paid = balance,
 *  and that balance is the next month's `brought_forward`. */
export interface MonthlyLedgerRow {
  period: string;
  period_month: number;
  period_year: number;
  label: string;
  brought_forward: string;
  rent: string;
  vat: string;
  other_charges: string;
  waived: string;
  total_due: string;
  paid: string;
  balance: string;
  /** True when the row is a balance carried from before the books began rather
   *  than a month that was billed — its figure sits in `brought_forward`. */
  is_opening: boolean;
}

export interface TenantPaymentHistory {
  total_paid: string;
  total_arrears: string;
  security_deposit: string;
  monthly_ledger: MonthlyLedgerRow[];
  payments: {
    id: number;
    amount: string;
    payment_date: string;
    period_month: number;
    period_year: number;
    source: string;
    reference: string;
  }[];
  /** `expected` is the full obligation (rent + VAT) that `balance` is measured
   *  against; the two components are broken out for commercial units. */
  arrears: {
    period: string;
    expected: string;
    expected_rent: string;
    expected_vat: string;
    paid: string;
    balance: string;
  }[];
}

export function usePaymentHistory(id: number | string | null) {
  return useQuery<TenantPaymentHistory>({
    queryKey: ["tenants", id, "payment-history"],
    queryFn: async () => {
      const { data } = await api.get(`/tenants/${id}/payment-history/`);
      return data;
    },
    enabled: !!id,
  });
}

export function useTenant(id: number | string | null) {
  return useQuery<TenantDetail>({
    queryKey: ["tenants", id],
    queryFn: async () => {
      const { data } = await api.get(`/tenants/${id}/`);
      return data;
    },
    enabled: !!id,
  });
}

export function useCreateTenant() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: Record<string, unknown>) => {
      const { data } = await api.post("/tenants/", payload);
      return data as TenantDetail;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tenants"] });
      qc.invalidateQueries({ queryKey: ["units"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export function useUpdateTenant(id: number | string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: Record<string, unknown>) => {
      const { data } = await api.patch(`/tenants/${id}/`, payload);
      return data as TenantDetail;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tenants"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export function useMoveOutNotice(id: number | string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: { notice_date: string; intended_move_out_date: string; notes?: string }) => {
      const { data } = await api.post(`/tenants/${id}/move-out-notice/`, payload);
      return data as TenantDetail;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tenants"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export function useMoveOutTenant(id: number | string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: { move_out_date?: string; notes?: string; deposit_refund_percentage?: number }) => {
      const { data } = await api.post(`/tenants/${id}/move-out/`, payload);
      return data as TenantDetail;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tenants"] });
      qc.invalidateQueries({ queryKey: ["units"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export function useUploadDocument(tenantId: number | string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (formData: FormData) => {
      const { data } = await api.post(`/tenants/${tenantId}/documents/`, formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tenants", tenantId] });
      qc.invalidateQueries({ queryKey: ["tenants"] });
    },
  });
}

export function useVerifyKyc(id: number | string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data } = await api.post(`/tenants/${id}/verify-kyc/`);
      return data as TenantDetail;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tenants"] });
    },
  });
}

export function useRejectKyc(id: number | string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: { reason: string }) => {
      const { data } = await api.post(`/tenants/${id}/reject-kyc/`, payload);
      return data as TenantDetail;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tenants"] });
    },
  });
}

/** Outcome of a statement email send — one entry per tenant that was asked for,
 *  including the ones that could not be sent, so the UI can name them. */
export interface StatementEmailResult {
  sent: number;
  failed: number;
  total: number;
  notifications: {
    id: number;
    tenant: number;
    tenant_name: string;
    unit_label: string;
    subject: string;
    status: "pending" | "sent" | "failed";
    error: string;
  }[];
}

/** Email one tenant their rent statement (PDF attached). */
export function useEmailStatement() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (tenantId: number | string) => {
      const { data } = await api.post(`/tenants/${tenantId}/email-statement/`);
      return data as StatementEmailResult;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["notifications"] });
    },
  });
}

/** Email a chosen set of tenants their rent statements in one go. */
export function useEmailStatements() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (tenantIds: number[]) => {
      const { data } = await api.post("/tenants/email-statements/", {
        tenant_ids: tenantIds,
      });
      return data as StatementEmailResult;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["notifications"] });
    },
  });
}
