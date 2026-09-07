import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

export interface UtilityCharge {
  id: number;
  tenant: number;
  tenant_name: string;
  unit_label: string;
  building_name: string;
  posting_date: string;
  period_month: number;
  period_year: number;
  label: string;
  opening_reading: string | null;
  closing_reading: string | null;
  units: string | null;
  amount: string;
  notes: string;
}

export interface PreviousReading {
  tenant: number;
  previous_reading: string | null;
  water_rate_per_unit: string;
}

export function useUtilityCharges(tenant?: number | null) {
  return useQuery<UtilityCharge[]>({
    queryKey: ["utility-charges", tenant],
    queryFn: async () => {
      const { data } = await api.get("/utility-charges/", {
        params: tenant ? { tenant } : {},
      });
      return data;
    },
  });
}

/**
 * Pre-fills the form's previous reading + shows the building tariff.
 *
 * Scoped to the period being entered. "The previous reading" only means
 * something relative to a month: without the period, backfilling a missed
 * month pre-fills it with a *later* month's closing figure and the form
 * presents a wrong bill as the safe default.
 */
export function usePreviousReading(
  tenant: number | null,
  month?: number,
  year?: number,
) {
  return useQuery<PreviousReading>({
    queryKey: ["utility-charges", "previous", tenant, month, year],
    queryFn: async () => {
      const { data } = await api.get("/utility-charges/previous-reading/", {
        params: { tenant, month, year },
      });
      return data;
    },
    enabled: !!tenant,
  });
}

export function useCaptureReading() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: Record<string, unknown>) => {
      const { data } = await api.post("/utility-charges/reading/", payload);
      return data as UtilityCharge;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["utility-charges"] });
      void qc.invalidateQueries({ queryKey: ["tenants"] });
    },
  });
}
