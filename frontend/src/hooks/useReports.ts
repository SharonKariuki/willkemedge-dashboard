import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";

/**
 * Filters a report understands. Blank values are dropped before the request,
 * so "All buildings" is simply no `building` parameter.
 */
export type ReportParams = Record<string, string | number | null | undefined>;

function clean(params: ReportParams): Record<string, string | number> {
  const out: Record<string, string | number> = {};
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") out[key] = value;
  }
  return out;
}

/**
 * Every report reads live figures. A report is never served from cache when
 * it is opened or the window regains focus, so a payment recorded a moment
 * ago is in the next view. While a new month or building loads, the previous
 * figures stay on screen instead of flashing a skeleton — but not when the
 * report is about a different thing (another tenant, another accounting tab),
 * where showing the old one even briefly would be wrong.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function useReport<T = any>(
  path: string,
  params: ReportParams = {},
  enabled = true,
  keepPrevious = true,
) {
  const query = clean(params);
  return useQuery<T>({
    queryKey: ["reports", path, query],
    queryFn: async () => {
      const { data } = await api.get(path, { params: query });
      return data as T;
    },
    enabled,
    staleTime: 0,
    refetchOnMount: "always",
    refetchOnWindowFocus: true,
    // While a report is on screen it keeps itself current: payments arrive
    // from the bank feed without anyone touching this tab.
    refetchInterval: 60_000,
    placeholderData: keepPrevious ? keepPreviousData : undefined,
  });
}

export function useMonthlyCollection(month: number, year: number, filters: ReportParams = {}) {
  return useReport("/reports/monthly-collection/", { month, year, ...filters });
}

export function useAnnualIncome(year: number, filters: ReportParams = {}) {
  return useReport("/reports/annual-income/", { year, ...filters });
}

export function useArrearsReport(filters: ReportParams = {}) {
  return useReport("/reports/arrears/", filters);
}

export function useTenantHistory(tenantId: number | string | null, months = 12) {
  return useReport(`/reports/tenant-history/${tenantId}/`, { months }, !!tenantId, false);
}

export function useOccupancyReport(filters: ReportParams = {}) {
  return useReport("/reports/occupancy/", filters);
}

export function useMoveLog(filters: ReportParams = {}) {
  return useReport("/reports/move-log/", filters);
}

export function useProfitLoss(month: number, year: number, building?: number | null) {
  return useReport("/reports/profit-loss/", { month, year, mode: "monthly", building });
}

export function useProfitLossAnnual(year: number, building?: number | null) {
  return useReport("/reports/profit-loss/", { year, mode: "annual", building });
}

export function useTrialBalance(month: number, year: number, building?: number | null) {
  return useReport("/reports/trial-balance/", { month, year, building });
}

export function useExpenseBreakdown(month: number, year: number, building?: number | null) {
  return useReport("/reports/expense-breakdown/", { month, year, building });
}

export function useRentBalances(month: number, year: number, filters: ReportParams = {}) {
  return useReport("/reports/rent-balances/", { month, year, ...filters });
}

export function useRentOverpayments(month: number, year: number, filters: ReportParams = {}) {
  return useReport("/reports/rent-overpayments/", { month, year, ...filters });
}

export function useAgingArrears(filters: ReportParams = {}) {
  return useReport("/reports/aging-arrears/", filters);
}

export function useExpiringLeases(filters: ReportParams = {}) {
  return useReport("/reports/expiring-leases/", filters);
}

export function useVacantUnits(filters: ReportParams = {}) {
  return useReport("/reports/vacant-units/", filters);
}

export function useUnitStatement(unitId: number | string | null, filters: ReportParams = {}) {
  return useReport(`/reports/unit-statement/${unitId}/`, filters, !!unitId, false);
}

export function useTenantStatement(tenantId: number | string | null, filters: ReportParams = {}) {
  return useReport(`/reports/tenant-statement/${tenantId}/`, filters, !!tenantId, false);
}

export function useLandlordStatement(month: number, year: number, filters: ReportParams = {}) {
  return useReport("/reports/landlord-statement/", { month, year, ...filters });
}
