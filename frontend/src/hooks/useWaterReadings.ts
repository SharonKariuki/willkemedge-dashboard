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

/** Pre-fills the form's previous reading + shows the building tariff. */
export function usePreviousReading(tenant: number | null) {
  return useQuery<PreviousReading>({
    queryKey: ["utility-charges", "previous", tenant],
    queryFn: async () => {
      const { data } = await api.get("/utility-charges/previous-reading/", {
        params: { tenant },
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
