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

/**
 * The Africa's Talking SMS wallet — what is left, and how to top it up.
 *
 * `balance` is a decimal string and can be null: a failed lookup must not be
 * mistaken for an empty wallet, so the server sends null plus `error` rather
 * than 0. Callers render "unavailable", never "KES 0".
 */
export interface SmsBalance {
  configured: boolean;
  balance: string | null;
  currency: string;
  sms_remaining: number | null;
  unit_cost: string;
  low: boolean;
  low_threshold: string;
  checked_at: string;
  cached: boolean;
  error: string | null;
  topup: { paybill: string; account: string; note: string };
}

export const SMS_BALANCE_KEY = ["notifications", "sms-balance"];

export function useSmsBalance() {
  return useQuery<SmsBalance>({
    queryKey: SMS_BALANCE_KEY,
    queryFn: async () => {
      const { data } = await api.get<SmsBalance>("/notifications/sms-balance/");
      return data;
    },
    // The server already caches for a minute. This card sits on three pages —
    // without a matching client stale time, moving between them would re-ask
    // Africa's Talking for a number that barely moves.
    staleTime: 1000 * 60,
  });
}

/**
 * Force a fresh read of the wallet, past both caches.
 *
 * A plain `refetch()` is not enough: it clears React Query's stale window but
 * still lands on the server's own 60s cache, so someone who has just loaded
 * airtime taps Refresh and sees the old balance stare back. `?refresh=1` is
 * the only thing that reaches Africa's Talking, and the result is written
 * straight into the shared query cache so all three cards update together.
 */
export function useRefreshSmsBalance() {
  const qc = useQueryClient();
  return useMutation<SmsBalance>({
    mutationFn: async () => {
      const { data } = await api.get<SmsBalance>("/notifications/sms-balance/", {
        params: { refresh: 1 },
      });
      return data;
    },
    onSuccess: (data) => qc.setQueryData(SMS_BALANCE_KEY, data),
  });
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
