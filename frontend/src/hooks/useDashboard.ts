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

export interface DashboardAlert {
  type: "overdue" | "partial";
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
    refetchInterval: 30_000,
  });
}
