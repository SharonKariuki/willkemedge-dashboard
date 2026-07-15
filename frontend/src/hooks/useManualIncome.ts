import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

export interface ManualIncome {
  id: number;
  date: string;
  building: number;
  building_name: string;
  account: number;
  account_code: string;
  account_name: string;
  amount: string;
  description: string;
  reference: string;
  period_month: number;
  period_year: number;
  notes: string;
}

export function useManualIncome(month?: number, year?: number, building?: number | null) {
  return useQuery<ManualIncome[]>({
    queryKey: ["manual-income", month, year, building],
    queryFn: async () => {
      const params: Record<string, number> = {};
      if (month && year) { params.month = month; params.year = year; }
      if (building) params.building = building;
      const { data } = await api.get("/manual-income/", { params });
      return data;
    },
  });
}

export function useIncomeAccounts() {
  return useQuery<{ id: number; code: string; name: string }[]>({
    queryKey: ["accounts", "income"],
    queryFn: async () => {
      const { data } = await api.get("/accounting/accounts/", { params: { type: "income" } });
      return data;
    },
  });
}

export function useCreateManualIncome() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: Record<string, unknown>) => {
      const { data } = await api.post("/manual-income/", payload);
      return data as ManualIncome;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["manual-income"] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export function useDeleteManualIncome() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => { await api.delete(`/manual-income/${id}/`); },
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["manual-income"] }),
  });
}
