import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { propertyImage } from "@/lib/images";
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

// ─── Cover photos ────────────────────────────────────────────────────────────
// The API needs the login token, which an <img src> cannot send, so the photo
// is fetched as a blob and shown through an object URL. Keyed apart from
// ["buildings"] so refreshing the list does not re-download every photo; the
// version in the key does that when a photo actually changes.

/** The photo to show for a building: its own, or the stock placeholder. */
export function useBuildingPhotoSrc(
  building: Pick<Building, "id" | "name" | "has_photo" | "photo_version"> | undefined,
  size: "sm" | "md" | "lg" = "md",
): string {
  const placeholder = building ? propertyImage(building.id ?? building.name, size) : "";
  const { data: blob } = useQuery<Blob>({
    queryKey: ["building-photo", building?.id, building?.photo_version],
    queryFn: async () => {
      const { data } = await api.get<Blob>(`/buildings/${building?.id}/photo/`, { responseType: "blob" });
      return data;
    },
    enabled: Boolean(building?.id && building?.has_photo),
    staleTime: Infinity,
    retry: false,
  });
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!blob || !building?.has_photo) {
      setUrl(null);
      return;
    }
    const next = URL.createObjectURL(blob);
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [blob, building?.has_photo]);
  return url ?? placeholder;
}

export function useSetBuildingPhoto() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, photo }: { id: number | string; photo: Blob }) => {
      const body = new FormData();
      body.append("photo", photo, "photo.jpg");
      const { data } = await api.put(`/buildings/${id}/photo/`, body);
      return data as Building;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["buildings"] }),
  });
}

export function useRemoveBuildingPhoto() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number | string) => {
      await api.delete(`/buildings/${id}/photo/`);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["buildings"] }),
  });
}
