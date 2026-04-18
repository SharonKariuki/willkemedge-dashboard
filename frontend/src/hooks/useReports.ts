import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";

export function useMonthlyCollection(month?: number, year?: number) {
  const now = new Date();
  const m = month ?? now.getMonth() + 1;
  const y = year ?? now.getFullYear();
  return useQuery({
    queryKey: ["reports", "monthly", m, y],
    queryFn: async () => {
      const { data } = await api.get("/reports/monthly-collection/", { params: { month: m, year: y } });
      return data;
    },
  });
}

export function useAnnualIncome(year?: number) {
  const y = year ?? new Date().getFullYear();
  return useQuery({
    queryKey: ["reports", "annual", y],
    queryFn: async () => {
      const { data } = await api.get("/reports/annual-income/", { params: { year: y } });
      return data;
    },
  });
}

export function useArrearsReport() {
  return useQuery({
    queryKey: ["reports", "arrears"],
    queryFn: async () => {
      const { data } = await api.get("/reports/arrears/");
      return data;
    },
  });
}

export function useTenantHistory(tenantId: number | string | null) {
  return useQuery({
    queryKey: ["reports", "tenant-history", tenantId],
    queryFn: async () => {
      const { data } = await api.get(`/reports/tenant-history/${tenantId}/`);
      return data;
    },
    enabled: !!tenantId,
  });
}

export function useOccupancyReport() {
  return useQuery({
    queryKey: ["reports", "occupancy"],
    queryFn: async () => {
      const { data } = await api.get("/reports/occupancy/");
      return data;
    },
  });
}

export function useMoveLog() {
  return useQuery({
    queryKey: ["reports", "move-log"],
    queryFn: async () => {
      const { data } = await api.get("/reports/move-log/");
      return data;
    },
  });
}

function withBuilding<T extends Record<string, unknown>>(params: T, building?: number | null): T {
  if (typeof building === "number") return { ...params, building } as T;
  return params;
}

export function useProfitLoss(month: number, year: number, building?: number | null) {
  return useQuery({
    queryKey: ["reports", "profit-loss", "monthly", month, year, building ?? null],
    queryFn: async () => {
      const { data } = await api.get("/reports/profit-loss/", {
        params: withBuilding({ month, year, mode: "monthly" }, building),
      });
      return data;
    },
  });
}

export function useProfitLossAnnual(year: number, building?: number | null) {
  return useQuery({
    queryKey: ["reports", "profit-loss", "annual", year, building ?? null],
    queryFn: async () => {
      const { data } = await api.get("/reports/profit-loss/", {
        params: withBuilding({ year, mode: "annual" }, building),
      });
      return data;
    },
  });
}

export function useTrialBalance(month: number, year: number, building?: number | null) {
  return useQuery({
    queryKey: ["reports", "trial-balance", month, year, building ?? null],
    queryFn: async () => {
      const { data } = await api.get("/reports/trial-balance/", {
        params: withBuilding({ month, year }, building),
      });
      return data;
    },
  });
}

export function useExpenseBreakdown(month: number, year: number, building?: number | null) {
  return useQuery({
    queryKey: ["reports", "expense-breakdown", month, year, building ?? null],
    queryFn: async () => {
      const { data } = await api.get("/reports/expense-breakdown/", {
        params: withBuilding({ month, year }, building),
      });
      return data;
    },
  });
}
