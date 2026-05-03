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

export function useReportsAccounting(tab: string, month: number, year: number) {
  return useQuery({
    queryKey: ["reports", "accounting", tab, month, year],
    queryFn: async () => {
      const { data } = await api.get("/reports/accounting/", {
        params: { tab, month, year },
      });
      return data as Record<string, unknown>;
    },
  });
}

export function useRentBalances(month: number, year: number) {
  return useQuery({
    queryKey: ["reports", "rent-balances", month, year],
    queryFn: async () => {
      const { data } = await api.get("/reports/rent-balances/", { params: { month, year } });
      return data;
    },
  });
}

export function useRentOverpayments(month: number, year: number) {
  return useQuery({
    queryKey: ["reports", "overpayments", month, year],
    queryFn: async () => {
      const { data } = await api.get("/reports/rent-overpayments/", { params: { month, year } });
      return data;
    },
  });
}

export function useAgingArrears() {
  return useQuery({
    queryKey: ["reports", "aging-arrears"],
    queryFn: async () => {
      const { data } = await api.get("/reports/aging-arrears/");
      return data;
    },
  });
}

export function useExpiringLeases() {
  return useQuery({
    queryKey: ["reports", "expiring-leases"],
    queryFn: async () => {
      const { data } = await api.get("/reports/expiring-leases/");
      return data;
    },
  });
}

export function useVacantUnits() {
  return useQuery({
    queryKey: ["reports", "vacant-units"],
    queryFn: async () => {
      const { data } = await api.get("/reports/vacant-units/");
      return data;
    },
  });
}

export function useUnitStatement(unitId: number | string | null) {
  return useQuery({
    queryKey: ["reports", "unit-statement", unitId],
    queryFn: async () => {
      const { data } = await api.get(`/reports/unit-statement/${unitId}/`);
      return data;
    },
    enabled: !!unitId,
  });
}

export function useTenantStatement(tenantId: number | string | null) {
  return useQuery({
    queryKey: ["reports", "tenant-statement", tenantId],
    queryFn: async () => {
      const { data } = await api.get(`/reports/tenant-statement/${tenantId}/`);
      return data;
    },
    enabled: !!tenantId,
  });
}

export function useLandlordStatement(month: number, year: number) {
  return useQuery({
    queryKey: ["reports", "landlord-statement", month, year],
    queryFn: async () => {
      const { data } = await api.get("/reports/landlord-statement/", { params: { month, year } });
      return data;
    },
  });
}
