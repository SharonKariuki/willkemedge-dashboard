import { useInfiniteQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { ActivityRow, ActivitySource } from "@/lib/activity";

export interface ActivityFilters {
  /** A user id, or "system". */
  actor?: string;
  source?: ActivitySource | "";
  financial?: boolean;
  /** ISO YYYY-MM-DD. */
  date_from?: string;
  date_to?: string;
  q?: string;
}

export interface ActivityPerson {
  id: number;
  label: string;
  role: string;
}

interface ActivityPage {
  results: ActivityRow[];
  next_before: number | null;
  /** Only on the first page. */
  people?: ActivityPerson[];
}

export function useActivity(filters: ActivityFilters, enabled = true) {
  return useInfiniteQuery({
    queryKey: ["activity", filters],
    enabled,
    queryFn: async ({ pageParam }) => {
      const params: Record<string, string | number> = {};
      if (filters.actor) params.actor = filters.actor;
      if (filters.source) params.source = filters.source;
      if (filters.financial) params.financial = "1";
      if (filters.date_from) params.date_from = filters.date_from;
      if (filters.date_to) params.date_to = filters.date_to;
      if (filters.q) params.q = filters.q;
      if (pageParam) params.before = pageParam;
      const { data } = await api.get<ActivityPage>("/auth/activity/", { params });
      return data;
    },
    initialPageParam: null as number | null,
    getNextPageParam: (last) => last.next_before,
  });
}
