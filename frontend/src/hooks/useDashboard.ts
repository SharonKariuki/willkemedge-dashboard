import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";

export interface DashboardKPIs {
  total_units: number;
  occupied: number;
  vacant: number;
  active_tenants: number;
  total_arrears: number;
  collection_expected: number;
  collection_received: number;
  collection_percentage: number;
  last_month_received: number;
}

export interface IncomeTrendPoint {
  month: string;
  amount: number;
}

export interface OccupancyBreakdown {
  vacant: number;
  paid: number;
  partial: number;
  unpaid: number;
  arrears: number;
}

export interface BuildingBreakdown {
  id: number;
  name: string;
  total: number;
  occupied: number;
  vacant: number;
}

export interface RecentPayment {
  id: number;
  tenant_name: string;
  unit_label: string;
  building_name: string;
  amount: number;
  source: string;
  payment_date: string;
  reference: string;
}

export type AlertType = "overdue" | "partial" | "move_out" | "expiring_lease" | "maintenance";

export interface DashboardAlert {
  type: AlertType;
  message: string;
  tenant_id?: number;
  unit_id?: number;
}

export interface DashboardData {
  kpis: DashboardKPIs;
  income_trend: IncomeTrendPoint[];
  occupancy: OccupancyBreakdown;
  buildings: BuildingBreakdown[];
  recent_payments: RecentPayment[];
  alerts: DashboardAlert[];
}

export function useDashboard() {
  return useQuery<DashboardData>({
    queryKey: ["dashboard"],
    queryFn: async () => {
      const { data } = await api.get("/dashboard/summary/");
      return data;
    },
    // Real-time: refresh every 15 seconds, never serve stale data from cache
    refetchInterval: 15_000,
    staleTime: 0,
    refetchOnWindowFocus: true,
  });
}
