import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

export interface NotificationTemplate {
  key: string;
  label: string;
  description: string;
  channel: "sms" | "email" | "both";
  subject: string;
  body: string;
}

export interface TenantNotification {
  id: number;
  tenant: number;
  tenant_name: string;
  unit_label: string;
  channel: "sms" | "email" | "both";
  channel_display: string;
  subject: string;
  body: string;
  status: "pending" | "sent" | "failed";
  sent_at: string | null;
  error: string;
  template_key: string;
  created_at: string;
}

export interface SendNotificationPayload {
  audience: "tenant" | "all_active" | "with_arrears";
  tenant_ids?: number[];
  channel: "sms" | "email" | "both";
  subject?: string;
  body: string;
  template_key?: string;
}

export interface SendNotificationResult {
  sent: number;
  failed: number;
  total: number;
  notifications: TenantNotification[];
}

export function useNotificationTemplates() {
  return useQuery<NotificationTemplate[]>({
    queryKey: ["notifications", "templates"],
    queryFn: async () => {
      const { data } = await api.get("/notifications/templates/");
      return data;
    },
    staleTime: 1000 * 60 * 10,
  });
}

export function useNotifications() {
  return useQuery<TenantNotification[]>({
    queryKey: ["notifications", "list"],
    queryFn: async () => {
      const { data } = await api.get("/notifications/");
      return data;
    },
  });
}

export function useSendNotification() {
  const qc = useQueryClient();
  return useMutation<SendNotificationResult, Error, SendNotificationPayload>({
    mutationFn: async (payload) => {
      const { data } = await api.post("/notifications/send/", payload);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["notifications"] });
    },
  });
}
