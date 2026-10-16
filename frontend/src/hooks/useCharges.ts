import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

import type { ChargeTypeValue, UtilityCharge } from "./useWaterReadings";

export interface ChargeTypeOption {
  value: ChargeTypeValue;
  label: string;
  /** "4200 Late Payment Fees / Penalties"; blank for a recharge, whose account is its expense. */
  account: string;
}

export interface ChargeOptions {
  charge_types: ChargeTypeOption[];
  expense_categories: { id: number; name: string; account: string }[];
}

export interface AddChargePayload {
  tenant: number;
  charge_type: ChargeTypeValue;
  amount: string;
  label: string;
  posting_date: string;
  period_month: number;
  period_year: number;
  expense_category?: number | null;
  notes?: string;
}

export function useChargeOptions(enabled = true) {
  return useQuery<ChargeOptions>({
    queryKey: ["utility-charges", "options"],
    queryFn: async () => {
      const { data } = await api.get("/utility-charges/options/");
      return data;
    },
    enabled,
    staleTime: 5 * 60 * 1000,
  });
}

/** Add Charge — owner only. A debit that is not rent, booked by its type. */
export function useAddCharge() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: AddChargePayload) => {
      const { data } = await api.post("/utility-charges/", payload);
      return data as UtilityCharge;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["utility-charges"] });
      void qc.invalidateQueries({ queryKey: ["credits"] });
      void qc.invalidateQueries({ queryKey: ["tenants"] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}
