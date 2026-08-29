/**
 * Shared tenant UI: form field, KYC panel, the rent-reminder (SMS/Email) modal,
 * and the statement-email confirmation. Extracted so the Tenants list, the
 * Tenant detail page and the Property page use the same building blocks.
 */
import { CheckCircle2, FileText, Mail, Phone, Send, ShieldCheck, Upload, XCircle, AlertTriangle } from "lucide-react";
import { cloneElement, isValidElement, useEffect, useId, useMemo, useRef, useState } from "react";
import toast from "react-hot-toast";

import { Badge, Button, Modal } from "@/components/ui";
import { useNotificationTemplates, useSendNotification } from "@/hooks/useNotifications";
import { useEmailStatements, useRejectKyc, useUploadDocument, useVerifyKyc } from "@/hooks/useTenants";
import { getErrorMessage } from "@/lib/apiError";
import { cn } from "@/lib/cn";
import type { KycStatus, TenantDetail, TenantListItem } from "@/lib/types";

export const inputCls =
  "w-full rounded-md bg-surface-raised hairline px-3 py-2.5 text-sm text-ink-900 placeholder:text-ink-400 focus:outline-none focus:ring-2 focus:ring-sage-500/40";

export function Field({
  label, error, children, className,
}: { label: string; error?: string; children: React.ReactNode; className?: string }) {
  const id = useId();
  // Associate the label with the control for assistive tech. The single child
  // control receives the generated id (unless it already has one).
  const control = isValidElement(children)
    ? cloneElement(children as React.ReactElement<{ id?: string }>, {
        id: (children as React.ReactElement<{ id?: string }>).props.id ?? id,
      })
    : children;
  return (
    <div className={className}>
      <label htmlFor={id} className="mb-1 block text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">{label}</label>
      {control}
      {error && <p className="mt-1 text-[11px] text-status-unpaid">{error}</p>}
    </div>
  );
}

// ─── KYC helpers ─────────────────────────────────────────────────────────────
export const KYC_TONE: Record<KycStatus, "paid" | "ochre" | "coral" | "neutral"> = {
  verified: "paid",
  pending: "ochre",
  rejected: "coral",
  not_started: "neutral",
};

export function KycBadge({ status, label }: { status: KycStatus; label: string }) {
  return <Badge tone={KYC_TONE[status]} withDot>KYC: {label}</Badge>;
}

const KYC_DOC_TYPES = [
  { value: "id_front", label: "ID — Front" },
  { value: "id_back", label: "ID — Back" },
  { value: "passport", label: "Passport" },
  { value: "kra_pin_certificate", label: "KRA PIN Certificate" },
] as const;

export function KycPanel({ tenant }: { tenant: TenantDetail }) {
  const upload = useUploadDocument(tenant.id);
  const verify = useVerifyKyc(tenant.id);
  const reject = useRejectKyc(tenant.id);
  const fileRef = useRef<HTMLInputElement>(null);
  const [docType, setDocType] = useState<string>("id_front");
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");

  const handleUpload = async (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("doc_type", docType);
    try {
      await upload.mutateAsync(fd);
      toast.success("Document uploaded");
    } catch {
      toast.error("Upload failed");
    }
  };

  const documents = tenant.documents ?? [];
  const missingItems = tenant.kyc_missing_items ?? [];
  const kycDocs = documents.filter((d) =>
    KYC_DOC_TYPES.some((t) => t.value === d.doc_type),
  );

  return (
    <div className="rounded-md border border-ink-100 p-4 dark:border-ink-700">
      <div className="mb-3 flex items-center justify-between">
        <p className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-wider text-ink-500">
          <ShieldCheck className="h-3.5 w-3.5" /> KYC Verification
        </p>
        <KycBadge status={tenant.kyc_status} label={tenant.kyc_status_display} />
      </div>

      {/* KRA PIN */}
      <div className="mb-3 flex justify-between gap-2 rounded-md bg-ink-50 px-3 py-2 text-sm dark:bg-ink-800">
        <span className="text-ink-500">KRA PIN</span>
        <span className="font-mono font-medium text-ink-900 dark:text-white">{tenant.kra_pin || "—"}</span>
      </div>

      {/* Missing items / reviewer notes */}
      {missingItems.length > 0 ? (
        <div className="mb-3 rounded-md bg-ochre-500/10 p-3 text-sm text-ink-700">
          <p className="font-medium text-ochre-700">Still needed before verification:</p>
          <ul className="mt-1 list-inside list-disc text-ink-600">
            {missingItems.map((m) => <li key={m}>{m}</li>)}
          </ul>
        </div>
      ) : tenant.kyc_status === "verified" ? (
        <div className="mb-3 rounded-md bg-status-paid/10 p-3 text-sm text-status-paid flex items-center gap-2">
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          Verified{tenant.kyc_verified_by_name ? ` by ${tenant.kyc_verified_by_name}` : ""}
          {tenant.kyc_verified_at ? ` on ${tenant.kyc_verified_at.slice(0, 10)}` : ""}.
        </div>
      ) : null}
      {tenant.kyc_status === "rejected" && tenant.kyc_notes && (
        <div className="mb-3 rounded-md bg-status-unpaid/10 p-3 text-sm text-status-unpaid">
          <span className="font-medium">Rejected:</span> {tenant.kyc_notes}
        </div>
      )}

      {/* Document list */}
      {kycDocs.length > 0 && (
        <ul className="mb-3 space-y-1.5">
          {kycDocs.map((d) => (
            <li key={d.id} className="flex items-center justify-between gap-2 rounded-md bg-ink-50 px-3 py-1.5 text-xs dark:bg-ink-800">
              <span className="flex items-center gap-1.5 text-ink-700 dark:text-ink-200">
                <FileText className="h-3.5 w-3.5 text-ink-400" />
                {d.doc_type_display}
                <span className="text-ink-400">· {d.original_name}</span>
              </span>
              <a href={d.file} target="_blank" rel="noreferrer" className="text-sage-600 hover:underline">View</a>
            </li>
          ))}
        </ul>
      )}

      {/* Upload */}
      <div className="mb-3 flex flex-wrap items-end gap-2">
        <Field label="Document type" className="flex-1 min-w-[160px]">
          <select value={docType} onChange={(e) => setDocType(e.target.value)} className={inputCls}>
            {KYC_DOC_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
        </Field>
        <input
          ref={fileRef}
          type="file"
          accept="image/*,application/pdf"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) handleUpload(f);
            e.target.value = "";
          }}
        />
        <Button type="button" variant="glass" size="sm" loading={upload.isPending} onClick={() => fileRef.current?.click()}>
          <Upload className="h-3.5 w-3.5" /> Upload
        </Button>
      </div>

      {/* Verify / reject actions */}
      {tenant.kyc_status !== "verified" && (
        rejecting ? (
          <div className="space-y-2">
            <Field label="Rejection reason">
              <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2} className={inputCls} placeholder="What's wrong / what the tenant needs to re-submit…" />
            </Field>
            <div className="flex justify-end gap-2">
              <Button type="button" variant="ghost" size="sm" onClick={() => { setRejecting(false); setReason(""); }}>Cancel</Button>
              <Button
                type="button" variant="danger" size="sm" loading={reject.isPending} disabled={!reason.trim()}
                onClick={async () => {
                  try { await reject.mutateAsync({ reason: reason.trim() }); toast.success("KYC rejected"); setRejecting(false); setReason(""); }
                  catch { toast.error("Failed"); }
                }}
              >
                <XCircle className="h-3.5 w-3.5" /> Confirm rejection
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex justify-end gap-2">
            {(tenant.kyc_status === "pending" || tenant.kyc_status === "rejected") && (
              <Button type="button" variant="ghost" size="sm" onClick={() => setRejecting(true)}>Reject</Button>
            )}
            <Button
              type="button" size="sm" loading={verify.isPending} disabled={missingItems.length > 0}
              onClick={async () => {
                try { await verify.mutateAsync(); toast.success("KYC verified"); }
                catch (e) {
                  const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
                  toast.error(detail ?? "Failed to verify");
                }
              }}
            >
              <ShieldCheck className="h-3.5 w-3.5" /> Mark verified
            </Button>
          </div>
        )
      )}
    </div>
  );
}

// ─── Rent reminder (SMS / Email) ─────────────────────────────────────────────
// Fill the template's {placeholders} from the tenant so Osoro previews the exact
// message. The backend also resolves placeholders on send, but we send the
// already-resolved text so what he sees is what goes out (WYSIWYG).
export function fillPlaceholders(text: string, t: TenantListItem): string {
  const now = new Date();
  const month = now.getMonth() + 1;
  const year = now.getFullYear();
  const dueDay = t.due_day || 5;
  const dueDate = `${year}-${String(month).padStart(2, "0")}-${String(dueDay).padStart(2, "0")}`;
  const first = t.first_name || t.full_name.split(" ")[0] || "";
  return text
    .replaceAll("{tenant_name}", t.full_name)
    .replaceAll("{first_name}", first)
    .replaceAll("{unit_label}", t.unit_label)
    .replaceAll("{building_name}", t.building_name)
    .replaceAll("{month}", String(month))
    .replaceAll("{year}", String(year))
    .replaceAll("{amount}", Number(t.monthly_rent).toLocaleString())
    .replaceAll("{balance}", Number(t.balance).toLocaleString())
    .replaceAll("{due_date}", dueDate);
}

// Rent-related templates, most-relevant first for an arrears reminder.
const REMINDER_TEMPLATE_KEYS = ["rent_overdue", "rent_reminder"];

type ReminderChannel = "sms" | "email" | "both";

const CHANNEL_OPTIONS: { value: ReminderChannel; label: string }[] = [
  { value: "sms", label: "SMS" },
  { value: "email", label: "Email" },
  { value: "both", label: "Both" },
];

export function RemindModal({ tenant, onClose }: { tenant: TenantListItem; onClose: () => void }) {
  const { data: templates } = useNotificationTemplates();
  const send = useSendNotification();
  const [templateKey, setTemplateKey] = useState(REMINDER_TEMPLATE_KEYS[0]);
  const [channel, setChannel] = useState<ReminderChannel>(tenant.phone ? "sms" : "email");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");

  const reminderTemplates = useMemo(
    () => (templates ?? []).filter((t) => REMINDER_TEMPLATE_KEYS.includes(t.key)),
    [templates],
  );

  // Reset the editable subject + body whenever the chosen template (or its data) loads.
  useEffect(() => {
    const tpl = reminderTemplates.find((t) => t.key === templateKey);
    if (tpl) {
      setBody(fillPlaceholders(tpl.body, tenant));
      setSubject(fillPlaceholders(tpl.subject, tenant));
    }
  }, [templateKey, reminderTemplates, tenant]);

  const hasPhone = Boolean(tenant.phone);
  const hasEmail = Boolean(tenant.email);
  const needsPhone = channel === "sms" || channel === "both";
  const needsEmail = channel === "email" || channel === "both";
  const missingPhone = needsPhone && !hasPhone;
  const missingEmail = needsEmail && !hasEmail;
  const canSend =
    body.trim().length > 0 &&
    !missingPhone &&
    !missingEmail &&
    !(needsEmail && !subject.trim()) &&
    !send.isPending;

  const handleSend = async () => {
    try {
      const res = await send.mutateAsync({
        audience: "tenant",
        tenant_ids: [tenant.id],
        channel,
        template_key: templateKey,
        subject: needsEmail ? subject.trim() : "",
        body: body.trim(),
      });
      if (res.sent > 0) {
        toast.success(`Reminder sent to ${tenant.full_name}`);
        onClose();
      } else {
        const err = res.notifications?.[0]?.error;
        toast.error(err ? `Could not send: ${err}` : "The reminder could not be sent.");
      }
    } catch (e) {
      toast.error(getErrorMessage(e, "Failed to send the reminder"));
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      size="md"
      eyebrow={`${tenant.building_name} · ${tenant.unit_label}`}
      title="Send rent reminder"
    >
      <div className="space-y-4">
        <div className="flex items-center justify-between gap-3 rounded-md bg-ink-50 px-3 py-2.5 text-sm dark:bg-ink-800">
          <div className="min-w-0">
            <p className="truncate font-medium text-ink-900 dark:text-white">{tenant.full_name}</p>
            <p className="flex items-center gap-1 text-[11px] text-ink-500">
              <Phone className="h-3 w-3" /> {tenant.phone || "No phone"}
              <span className="mx-1 text-ink-300">·</span>
              {tenant.email || "No email"}
            </p>
          </div>
          <div className="text-right">
            <p className="font-display text-lg font-semibold text-status-unpaid tabular-nums">
              KES {Number(tenant.balance).toLocaleString()}
            </p>
            <p className="text-[11px] text-ink-500">Outstanding</p>
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Template">
            <select
              value={templateKey}
              onChange={(e) => setTemplateKey(e.target.value)}
              className={inputCls}
            >
              {reminderTemplates.map((t) => (
                <option key={t.key} value={t.key}>{t.label}</option>
              ))}
            </select>
          </Field>

          <Field label="Send via">
            <div className="flex gap-1.5">
              {CHANNEL_OPTIONS.map((opt) => {
                const disabled =
                  (opt.value === "sms" && !hasPhone) ||
                  (opt.value === "email" && !hasEmail) ||
                  (opt.value === "both" && (!hasPhone || !hasEmail));
                return (
                  <button
                    key={opt.value}
                    type="button"
                    disabled={disabled}
                    onClick={() => setChannel(opt.value)}
                    className={cn(
                      "flex-1 rounded-md border px-2 py-2 text-xs font-medium transition-colors",
                      channel === opt.value
                        ? "border-teal-600 bg-teal-600/10 text-teal-700"
                        : "border-border text-content-muted hover:border-teal-600/50",
                      disabled && "cursor-not-allowed opacity-40 hover:border-border",
                    )}
                    title={disabled ? "Tenant is missing the required contact detail" : undefined}
                  >
                    {opt.label}
                  </button>
                );
              })}
            </div>
          </Field>
        </div>

        {needsEmail && (
          <Field label="Email subject">
            <input value={subject} onChange={(e) => setSubject(e.target.value)} className={inputCls} />
          </Field>
        )}

        <Field label="Message">
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={5}
            className={inputCls}
          />
        </Field>
        {needsPhone && (
          <p className="-mt-2 text-[11px] text-ink-500">
            {body.length} characters · {Math.max(1, Math.ceil(body.length / 160))} SMS segment(s).
          </p>
        )}

        {(missingPhone || missingEmail) && (
          <div className="rounded-md bg-status-unpaid/8 p-3 text-sm text-status-unpaid flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            {missingPhone && missingEmail
              ? "This tenant has no phone or email on file."
              : missingPhone
                ? "This tenant has no phone number on file, so SMS can't be sent."
                : "This tenant has no email address on file, so email can't be sent."}
            {" "}Add it on their profile, or pick another channel.
          </div>
        )}

        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="button" onClick={handleSend} loading={send.isPending} disabled={!canSend}>
            <Send className="h-4 w-4" /> Send {channel === "both" ? "reminder" : channel === "email" ? "email" : "SMS"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

// ─── Email statements to a chosen set of tenants ─────────────────────────────
/** Confirmation step before statements leave the building. Sending is
 *  outward-facing and cannot be recalled, so the office sees exactly who is
 *  about to be written to before it fires. */
export function EmailStatementsModal({
  tenants, scopeLabel, onClose, onSent,
}: {
  tenants: TenantListItem[];
  /** Names what the set is, when it came from somewhere other than hand-picked
   *  rows — e.g. every current tenant in one property. */
  scopeLabel?: string;
  onClose: () => void;
  onSent: () => void;
}) {
  const emailStatements = useEmailStatements();

  const handleSend = async () => {
    try {
      const res = await emailStatements.mutateAsync(tenants.map((t) => t.id));
      if (res.sent > 0) {
        toast.success(
          res.failed > 0
            ? `${res.sent} statement${res.sent === 1 ? "" : "s"} sent · ${res.failed} failed`
            : `${res.sent} statement${res.sent === 1 ? "" : "s"} sent`,
        );
      } else {
        toast.error("No statements could be sent. Check the Notifications page for why.");
      }
      // Failures are on record either way, so the selection is cleared and the
      // office follows them up from the notification history rather than
      // guessing which of the ticked rows went out.
      onSent();
      onClose();
    } catch (e) {
      toast.error(getErrorMessage(e, "Failed to email the statements"));
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      size="md"
      eyebrow="Rent statements"
      title={`Email ${tenants.length} statement${tenants.length === 1 ? "" : "s"}`}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose} disabled={emailStatements.isPending}>
            Cancel
          </Button>
          <Button onClick={handleSend} loading={emailStatements.isPending}>
            <Mail className="h-4 w-4" /> Send now
          </Button>
        </div>
      }
    >
      <div className="space-y-3">
        <p className="text-sm text-ink-600 dark:text-ink-300">
          {scopeLabel ? `${scopeLabel} — each` : "Each"} tenant gets their current rent
          statement as a PDF attachment, showing the balance as at today.
        </p>
        <div className="max-h-56 overflow-y-auto rounded-md hairline p-2">
          <div className="grid gap-1">
            {tenants.map((t) => (
              <div key={t.id} className="flex items-center justify-between gap-2 px-2 py-1 text-xs">
                <span className="min-w-0 truncate font-medium text-ink-900 dark:text-white">
                  {t.full_name}
                  <span className="ml-1 font-normal text-ink-400">· {t.unit_label}</span>
                </span>
                <span className="shrink-0 truncate text-ink-500">{t.email}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </Modal>
  );
}
