import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { TenantDetail, TenantListItem } from "@/lib/types";

interface TenantFilters {
  status?: string;
  building?: number | string;
  unit?: number | string;
  search?: string;
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
    },
  });
}
