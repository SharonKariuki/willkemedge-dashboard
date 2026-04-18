import {
  AlertCircle,
  Bell,
  CheckCircle2,
  Mail,
  MessageSquare,
  Send,
  Sparkles,
  Users,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import toast from "react-hot-toast";

import {
  Badge,
  Button,
  Card,
  EmptyState,
  PageHeader,
  Skeleton,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "@/components/ui";
import {
  useNotifications,
  useNotificationTemplates,
  useSendNotification,
  type NotificationTemplate,
  type SendNotificationPayload,
} from "@/hooks/useNotifications";
import { useTenants } from "@/hooks/useTenants";
import { cn } from "@/lib/cn";

const AUDIENCE_OPTIONS: { value: SendNotificationPayload["audience"]; label: string; desc: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { value: "tenant", label: "Selected tenants", desc: "Pick specific tenants below", icon: Users },
  { value: "all_active", label: "All active tenants", desc: "Everyone currently occupying a unit", icon: Users },
  { value: "with_arrears", label: "Tenants with arrears", desc: "Only tenants with an open balance", icon: AlertCircle },
];

const CHANNEL_OPTIONS: { value: "sms" | "email" | "both"; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { value: "sms", label: "SMS", icon: MessageSquare },
  { value: "email", label: "Email", icon: Mail },
  { value: "both", label: "SMS + Email", icon: Send },
];

const inputCls =
  "w-full rounded-md bg-surface-raised hairline px-3 py-2.5 text-sm text-ink-900 placeholder:text-ink-400 focus:outline-none focus:ring-2 focus:ring-sage-500/40";

const PLACEHOLDERS = [
  "{tenant_name}",
  "{first_name}",
  "{unit_label}",
  "{building_name}",
  "{month}",
  "{year}",
  "{amount}",
  "{balance}",
  "{due_date}",
];

function StatusBadge({ status }: { status: "pending" | "sent" | "failed" }) {
  if (status === "sent")
    return (
      <Badge tone="sage" withDot>
        Sent
      </Badge>
    );
  if (status === "failed")
    return (
      <Badge tone="coral" withDot>
        Failed
      </Badge>
    );
  return (
    <Badge tone="neutral" withDot>
      Pending
    </Badge>
  );
}

export default function NotificationsPage() {
  const { data: templates, isLoading: templatesLoading } = useNotificationTemplates();
  const { data: tenants, isLoading: tenantsLoading } = useTenants({ status: "active" });
  const { data: history, isLoading: historyLoading } = useNotifications();
  const sendNotification = useSendNotification();

  const [selectedTemplate, setSelectedTemplate] = useState<string>("");
  const [audience, setAudience] = useState<SendNotificationPayload["audience"]>("tenant");
  const [selectedTenantIds, setSelectedTenantIds] = useState<number[]>([]);
  const [channel, setChannel] = useState<"sms" | "email" | "both">("sms");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");

  const template: NotificationTemplate | undefined = useMemo(
    () => templates?.find((t) => t.key === selectedTemplate),
    [templates, selectedTemplate]
  );

  useEffect(() => {
    if (template) {
      setSubject(template.subject);
      setBody(template.body);
      setChannel(template.channel);
    }
  }, [template]);

  const recipientCount = useMemo(() => {
    if (!tenants) return 0;
    if (audience === "all_active") return tenants.length;
    if (audience === "with_arrears") return tenants.length; // estimate; backend filters precisely
    return selectedTenantIds.length;
  }, [audience, tenants, selectedTenantIds]);

  const toggleTenant = (id: number) => {
    setSelectedTenantIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const resetCustom = () => {
    setSelectedTemplate("");
    setSubject("");
    setBody("");
  };

  const insertPlaceholder = (ph: string) => {
    setBody((b) => `${b}${b.endsWith(" ") || b.length === 0 ? "" : " "}${ph}`);
  };

  const submit = async () => {
    if (!body.trim()) {
      toast.error("Write a message before sending");
      return;
    }
    if (audience === "tenant" && selectedTenantIds.length === 0) {
      toast.error("Select at least one tenant");
      return;
    }
    try {
      const result = await sendNotification.mutateAsync({
        audience,
        tenant_ids: audience === "tenant" ? selectedTenantIds : [],
        channel,
        subject,
        body,
        template_key: selectedTemplate || "",
      });
      if (result.failed === 0) {
        toast.success(`Sent to ${result.sent} tenant${result.sent === 1 ? "" : "s"}`);
      } else {
        toast(`Sent ${result.sent} · ${result.failed} failed`, { icon: "⚠️" });
      }
      setSelectedTenantIds([]);
    } catch {
      toast.error("Failed to send notifications");
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Outreach"
        title="Notifications"
        description="Send SMS or email to tenants — pick a template or write your own."
      />

      {/* Templates */}
      <Card variant="glass" padding="md">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            <p className="font-display text-lg font-semibold text-ink-900">Pick a template</p>
            <p className="text-xs text-ink-500">
              Starting points you can edit before sending. Or write a custom message below.
            </p>
          </div>
          <Button variant="outline" size="sm" onClick={resetCustom}>
            <Sparkles className="h-3.5 w-3.5" />
            New message
          </Button>
        </div>

        {templatesLoading ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-24" />
            ))}
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {templates?.map((t) => {
              const active = selectedTemplate === t.key;
              return (
                <button
                  key={t.key}
                  type="button"
                  onClick={() => setSelectedTemplate(t.key)}
                  className={cn(
                    "rounded-md p-4 text-left transition-all",
                    active
                      ? "bg-ink-900 text-canvas shadow-float dark:bg-ink-100 dark:text-canvas"
                      : "glass text-ink-700 hover:shadow-float"
                  )}
                >
                  <div className="flex items-center gap-2">
                    <Bell className={cn("h-4 w-4", active ? "" : "text-ink-400")} />
                    <span className="font-medium">{t.label}</span>
                  </div>
                  <p className={cn("mt-1 text-[11px]", active ? "text-canvas/70" : "text-ink-500")}>
                    {t.description}
                  </p>
                  <p className={cn("mt-2 text-[10px] uppercase tracking-[0.14em]", active ? "text-canvas/50" : "text-ink-400")}>
                    {t.channel === "both" ? "SMS + Email" : t.channel}
                  </p>
                </button>
              );
            })}
          </div>
        )}
      </Card>

      {/* Compose */}
      <Card variant="glass" padding="md">
        <p className="mb-4 font-display text-lg font-semibold text-ink-900">Compose message</p>

        <div className="mb-4">
          <p className="mb-2 text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">
            Audience
          </p>
          <div className="grid gap-2 sm:grid-cols-3">
            {AUDIENCE_OPTIONS.map((opt) => {
              const Icon = opt.icon;
              const active = audience === opt.value;
              return (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setAudience(opt.value)}
                  className={cn(
                    "rounded-md p-3 text-left transition-all",
                    active
                      ? "bg-ink-900 text-canvas shadow-float dark:bg-ink-100 dark:text-canvas"
                      : "glass text-ink-700 hover:shadow-float"
                  )}
                >
                  <div className="flex items-center gap-2">
                    <Icon className="h-4 w-4" />
                    <span className="font-medium">{opt.label}</span>
                  </div>
                  <p className={cn("mt-1 text-[11px]", active ? "text-canvas/70" : "text-ink-500")}>
                    {opt.desc}
                  </p>
                </button>
              );
            })}
          </div>
        </div>

        {audience === "tenant" && (
          <div className="mb-4">
            <p className="mb-2 text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">
              Select tenants ({selectedTenantIds.length})
            </p>
            {tenantsLoading ? (
              <Skeleton className="h-24" />
            ) : !tenants?.length ? (
              <p className="text-xs text-ink-500">No active tenants found.</p>
            ) : (
              <div className="max-h-56 overflow-y-auto rounded-md hairline p-2">
                <div className="grid gap-1 sm:grid-cols-2 lg:grid-cols-3">
                  {tenants.map((t) => {
                    const selected = selectedTenantIds.includes(t.id);
                    return (
                      <label
                        key={t.id}
                        className={cn(
                          "flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-xs transition-all",
                          selected
                            ? "bg-sage-500/15 text-ink-900"
                            : "hover:bg-white/60 dark:hover:bg-white/5"
                        )}
                      >
                        <input
                          type="checkbox"
                          checked={selected}
                          onChange={() => toggleTenant(t.id)}
                          className="h-3.5 w-3.5 accent-sage-500"
                        />
                        <span className="truncate font-medium">{t.full_name}</span>
                        <span className="shrink-0 text-ink-400">· {t.unit_label}</span>
                      </label>
                    );
                  })}
                </div>
              </div>
            )}
            <div className="mt-2 flex gap-2">
              <button
                type="button"
                onClick={() => setSelectedTenantIds(tenants?.map((t) => t.id) ?? [])}
                className="text-[11px] font-medium text-sage-700 underline-offset-2 hover:underline dark:text-sage-400"
              >
                Select all
              </button>
              <button
                type="button"
                onClick={() => setSelectedTenantIds([])}
                className="text-[11px] font-medium text-ink-500 underline-offset-2 hover:underline"
              >
                Clear
              </button>
            </div>
          </div>
        )}

        <div className="mb-4">
          <p className="mb-2 text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">
            Channel
          </p>
          <div className="flex flex-wrap gap-2">
            {CHANNEL_OPTIONS.map((opt) => {
              const Icon = opt.icon;
              const active = channel === opt.value;
              return (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setChannel(opt.value)}
                  className={cn(
                    "flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-medium transition-all",
                    active
                      ? "bg-ink-900 text-canvas shadow-float dark:bg-ink-100 dark:text-canvas"
                      : "glass text-ink-700"
                  )}
                >
                  <Icon className="h-3.5 w-3.5" />
                  {opt.label}
                </button>
              );
            })}
          </div>
        </div>

        {(channel === "email" || channel === "both") && (
          <div className="mb-4">
            <label className="mb-1 block text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">
              Email subject
            </label>
            <input
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              placeholder="Subject line"
              className={inputCls}
            />
          </div>
        )}

        <div className="mb-3">
          <label className="mb-1 block text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">
            Message body
          </label>
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={6}
            placeholder="Write your message. You can use placeholders like {tenant_name} and {unit_label}."
            className={cn(inputCls, "resize-y font-mono text-[13px] leading-relaxed")}
          />
          <div className="mt-2 flex flex-wrap gap-1.5">
            <span className="text-[10px] uppercase tracking-[0.14em] text-ink-400">
              Insert:
            </span>
            {PLACEHOLDERS.map((ph) => (
              <button
                key={ph}
                type="button"
                onClick={() => insertPlaceholder(ph)}
                className="rounded-full bg-surface-raised px-2 py-0.5 text-[10px] font-mono text-ink-600 hairline hover:bg-sage-500/10"
              >
                {ph}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-ink-500">
            Ready to send to{" "}
            <span className="font-semibold text-ink-900">
              {audience === "with_arrears" ? "all tenants with arrears" : `${recipientCount} tenant${recipientCount === 1 ? "" : "s"}`}
            </span>{" "}
            via <span className="font-semibold text-ink-900">{channel === "both" ? "SMS + Email" : channel.toUpperCase()}</span>.
          </p>
          <Button onClick={submit} loading={sendNotification.isPending}>
            <Send className="h-4 w-4" />
            Send notification
          </Button>
        </div>
      </Card>

      {/* History */}
      <Card variant="glass" padding="md">
        <div className="mb-4 flex items-center gap-2">
          <CheckCircle2 className="h-4 w-4 text-sage-600 dark:text-sage-400" />
          <p className="font-display text-lg font-semibold text-ink-900">Recent sends</p>
        </div>
        {historyLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-12" />
            ))}
          </div>
        ) : !history?.length ? (
          <EmptyState
            icon={<Bell className="h-5 w-5" />}
            title="No notifications yet"
            description="Messages you send will show up here."
          />
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <THead>
                <TR>
                  <TH>Tenant</TH>
                  <TH>Channel</TH>
                  <TH>Subject / Preview</TH>
                  <TH>Status</TH>
                  <TH>When</TH>
                </TR>
              </THead>
              <TBody>
                {history.map((n) => (
                  <TR key={n.id}>
                    <TD className="font-medium text-ink-900">
                      {n.tenant_name}
                      <p className="text-[11px] text-ink-400">{n.unit_label}</p>
                    </TD>
                    <TD className="text-ink-500">{n.channel_display}</TD>
                    <TD className="max-w-sm">
                      {n.subject && (
                        <p className="truncate font-medium text-ink-900">{n.subject}</p>
                      )}
                      <p className="truncate text-[11px] text-ink-500">{n.body}</p>
                      {n.error && (
                        <p className="truncate text-[11px] text-status-unpaid">{n.error}</p>
                      )}
                    </TD>
                    <TD>
                      <StatusBadge status={n.status} />
                    </TD>
                    <TD className="text-[11px] text-ink-400">
                      {new Date(n.created_at).toLocaleString()}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </div>
        )}
      </Card>
    </div>
  );
}
