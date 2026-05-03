import {
  AlertCircle,
  Bell,
  CheckCircle2,
  ChevronDown,
  Mail,
  MessageSquare,
  Send,
  Sparkles,
  Users,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
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

// ─── Friendly placeholder definitions ────────────────────────────────────────
const SMART_INSERTS = [
  { label: "Tenant name", value: "{tenant_name}", example: "e.g. John Kamau" },
  { label: "First name only", value: "{first_name}", example: "e.g. John" },
  { label: "Unit number", value: "{unit_label}", example: "e.g. A3" },
  { label: "Building name", value: "{building_name}", example: "e.g. Maple Court" },
  { label: "Month", value: "{month}", example: "e.g. May" },
  { label: "Year", value: "{year}", example: "e.g. 2026" },
  { label: "Amount owed", value: "{amount}", example: "e.g. KES 15,000" },
  { label: "Balance remaining", value: "{balance}", example: "e.g. KES 5,000" },
  { label: "Due date", value: "{due_date}", example: "e.g. 5th May 2026" },
];

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

function StatusBadge({ status }: { status: "pending" | "sent" | "failed" }) {
  if (status === "sent") return <Badge tone="sage" withDot>Sent</Badge>;
  if (status === "failed") return <Badge tone="coral" withDot>Failed</Badge>;
  return <Badge tone="neutral" withDot>Pending</Badge>;
}

// ─── Smart Insert dropdown ────────────────────────────────────────────────────
function SmartInsertDropdown({ onInsert }: { onInsert: (value: string) => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    if (open) document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 rounded-full border border-ink-200 bg-surface-raised px-3 py-1.5 text-xs font-medium text-ink-700 hover:border-sage-400 hover:text-sage-700 transition-colors"
      >
        <Sparkles className="h-3.5 w-3.5" />
        Insert field
        <ChevronDown className={cn("h-3 w-3 transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div className="absolute left-0 top-[calc(100%+6px)] z-30 w-72 rounded-xl border border-ink-200 bg-white shadow-float dark:bg-ink-900 dark:border-ink-700">
          <div className="border-b border-ink-100 px-3 py-2.5 dark:border-ink-700">
            <p className="text-xs font-semibold text-ink-700 dark:text-ink-300">Auto-fill fields</p>
            <p className="text-[10px] text-ink-500 mt-0.5">Click to insert into your message</p>
          </div>
          <ul className="max-h-72 overflow-y-auto py-1">
            {SMART_INSERTS.map((item) => (
              <li key={item.value}>
                <button
                  type="button"
                  onClick={() => { onInsert(item.value); setOpen(false); }}
                  className="flex w-full items-start gap-3 px-3 py-2.5 text-left hover:bg-sage-50 dark:hover:bg-ink-800 transition-colors"
                >
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-medium text-ink-900 dark:text-white">{item.label}</p>
                    <p className="text-[10px] text-ink-500 mt-0.5">{item.example}</p>
                  </div>
                  <code className="shrink-0 rounded bg-ink-100 px-1.5 py-0.5 text-[10px] font-mono text-ink-600 dark:bg-ink-700 dark:text-ink-300">
                    {item.value}
                  </code>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default function NotificationsPage() {
  const { data: templates, isLoading: templatesLoading } = useNotificationTemplates();
  const { data: tenants, isLoading: tenantsLoading } = useTenants({ status: "active" });
  const { data: history, isLoading: historyLoading } = useNotifications();
  const sendNotification = useSendNotification();
  const bodyRef = useRef<HTMLTextAreaElement>(null);

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
    if (audience === "with_arrears") return tenants.length;
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

  // Insert at cursor position in textarea
  const insertAtCursor = (value: string) => {
    const ta = bodyRef.current;
    if (!ta) {
      setBody((b) => `${b}${b.endsWith(" ") || b.length === 0 ? "" : " "}${value} `);
      return;
    }
    const start = ta.selectionStart ?? body.length;
    const end = ta.selectionEnd ?? body.length;
    const before = body.substring(0, start);
    const after = body.substring(end);
    const spaceBefore = before.length > 0 && !before.endsWith(" ") ? " " : "";
    const newBody = `${before}${spaceBefore}${value} ${after}`;
    setBody(newBody);
    // Move cursor after inserted text
    requestAnimationFrame(() => {
      const pos = start + spaceBefore.length + value.length + 1;
      ta.setSelectionRange(pos, pos);
      ta.focus();
    });
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
        description="Send SMS or email to tenants — pick a template or write your own message."
      />

      {/* Templates */}
      <Card variant="glass" padding="md">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            <p className="font-display text-lg font-semibold text-ink-900">Pick a template</p>
            <p className="text-xs text-ink-500">
              Ready-made messages you can edit before sending. Or start fresh below.
            </p>
          </div>
          <Button variant="outline" size="sm" onClick={resetCustom}>
            <Sparkles className="h-3.5 w-3.5" />
            Write custom message
          </Button>
        </div>

        {templatesLoading ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-24" />)}
          </div>
        ) : !templates?.length ? (
          <p className="text-sm text-ink-500">No templates found. Configure templates in the backend admin.</p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {templates.map((t) => {
              const active = selectedTemplate === t.key;
              return (
                <button
                  key={t.key}
                  type="button"
                  onClick={() => setSelectedTemplate(active ? "" : t.key)}
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
                    {t.channel === "both" ? "SMS + Email" : t.channel.toUpperCase()}
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

        {/* Audience */}
        <div className="mb-4">
          <p className="mb-2 text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">Who should receive this?</p>
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

        {/* Tenant selector */}
        {audience === "tenant" && (
          <div className="mb-4">
            <p className="mb-2 text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">
              Select tenants ({selectedTenantIds.length} selected)
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
                          selected ? "bg-sage-500/15 text-ink-900" : "hover:bg-white/60 dark:hover:bg-white/5"
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

        {/* Channel */}
        <div className="mb-4">
          <p className="mb-2 text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">How to send?</p>
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
                    active ? "bg-ink-900 text-canvas shadow-float dark:bg-ink-100 dark:text-canvas" : "glass text-ink-700"
                  )}
                >
                  <Icon className="h-3.5 w-3.5" />
                  {opt.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Email subject */}
        {(channel === "email" || channel === "both") && (
          <div className="mb-4">
            <label className="mb-1 block text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">
              Email subject line
            </label>
            <input
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              placeholder="e.g. Rent reminder for May 2026"
              className={inputCls}
            />
          </div>
        )}

        {/* Message body */}
        <div className="mb-3">
          <div className="mb-2 flex items-center justify-between gap-3">
            <label className="text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">
              Message body
            </label>
            <SmartInsertDropdown onInsert={insertAtCursor} />
          </div>
          <textarea
            ref={bodyRef}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={7}
            placeholder={
              `Write your message here.\n\nTip: Use "Insert field" above to personalise — e.g. click "Tenant name" to add the tenant's name automatically.`
            }
            className={cn(inputCls, "resize-y leading-relaxed")}
          />
          {body && (
            <div className="mt-2 rounded-md border border-sage-200 bg-sage-50 px-3 py-2 text-xs text-sage-800 dark:border-sage-700 dark:bg-sage-900/20 dark:text-sage-300">
              <p className="font-medium mb-1">Preview (with example values):</p>
              <p className="whitespace-pre-wrap text-[11px]">
                {body
                  .replace("{tenant_name}", "John Kamau")
                  .replace("{first_name}", "John")
                  .replace("{unit_label}", "A3")
                  .replace("{building_name}", "Maple Court")
                  .replace("{month}", "May")
                  .replace("{year}", "2026")
                  .replace("{amount}", "KES 15,000")
                  .replace("{balance}", "KES 5,000")
                  .replace("{due_date}", "5th May 2026")}
              </p>
            </div>
          )}
        </div>

        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-ink-500">
            Sending to{" "}
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
            {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-12" />)}
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
                    <TD><StatusBadge status={n.status} /></TD>
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
