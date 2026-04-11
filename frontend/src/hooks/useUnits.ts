import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { Unit, UnitStatusSummary } from "@/lib/types";

interface UnitFilters {
  building?: number | string;
  status?: string;
  unit_type?: string;
}

export function useUnits(filters?: UnitFilters) {
  return useQuery<Unit[]>({
    queryKey: ["units", filters],
    queryFn: async () => {
      const { data } = await api.get("/units/", { params: filters });
      return data;
    },
  });
}

export function useUnitStatusSummary(buildingId?: number | string) {
  return useQuery<UnitStatusSummary>({
    queryKey: ["units", "status-summary", buildingId],
    queryFn: async () => {
      const params = buildingId ? { building: buildingId } : {};
      const { data } = await api.get("/units/status-summary/", { params });
      return data;
    },
  });
}

export function useCreateUnit() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: Partial<Unit>) => {
      const { data } = await api.post("/units/", payload);
      return data as Unit;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["units"] });
      qc.invalidateQueries({ queryKey: ["buildings"] });
    },
  });
}

export function useUpdateUnit(id: number | string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: Partial<Unit>) => {
      const { data } = await api.patch(`/units/${id}/`, payload);
      return data as Unit;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["units"] });
      qc.invalidateQueries({ queryKey: ["buildings"] });
    },
  });
}
