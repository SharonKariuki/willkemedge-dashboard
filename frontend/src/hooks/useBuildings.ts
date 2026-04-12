import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { Building, BuildingDetail, Unit } from "@/lib/types";

export function useBuildings() {
  return useQuery<Building[]>({
    queryKey: ["buildings"],
    queryFn: async () => {
      const { data } = await api.get("/buildings/");
      return data;
    },
  });
}

export function useBuilding(id: number | string) {
  return useQuery<BuildingDetail>({
    queryKey: ["buildings", id],
    queryFn: async () => {
      const { data } = await api.get(`/buildings/${id}/`);
      return data;
    },
    enabled: !!id,
  });
}

export function useCreateBuilding() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: Partial<Building>) => {
      const { data } = await api.post("/buildings/", payload);
      return data as Building;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["buildings"] }),
  });
}

export function useUpdateBuilding(id: number | string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: Partial<Building>) => {
      const { data } = await api.patch(`/buildings/${id}/`, payload);
      return data as Building;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["buildings"] });
      qc.invalidateQueries({ queryKey: ["buildings", id] });
    },
  });
}

export function useDeleteBuilding() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number | string) => {
      await api.delete(`/buildings/${id}/`);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["buildings"] }),
  });
}

export function useBulkCreateUnits(buildingId: number | string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (units: Partial<Unit>[]) => {
      const { data } = await api.post(`/buildings/${buildingId}/bulk-create-units/`, { units });
      return data as BuildingDetail;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["buildings"] });
      qc.invalidateQueries({ queryKey: ["units"] });
    },
  });
}
