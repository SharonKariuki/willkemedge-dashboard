/**
 * TenantsPage — complete rewrite.
 * Features:
 * - Group by building
 * - Active tenants first, moved-out tenants below
 * - Building filter tabs (auto-generated from buildings)
 * - Clickable tenant rows → detail modal
 * - Tenant detail: full info, analytics, deposit, edit, notice, move-out
 * - Date pickers system-wide
 */
import { zodResolver } from "@hookform/resolvers/zod";
import {
  AlertTriangle, CheckCircle2, Download, FileText, LogOut,
  Pencil, Phone, Plus, Search, ShieldCheck, Upload, UserPlus, X, XCircle,
} from "lucide-react";


import { cloneElement, isValidElement, useEffect, useId, useMemo, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import toast from "react-hot-toast";
import { useSearchParams } from "react-router-dom";
import { z } from "zod";

import {
  Badge, Button, Card, DatePicker, EmptyState, ErrorState, Input, Modal,
  PageHeader, Skeleton, Table, TBody, TD, TH, THead, TR,
} from "@/components/ui";
import {
  useCreateTenant, useMoveOutNotice, useMoveOutTenant,
  useRejectKyc, useTenant, useTenants, useUpdateTenant,
  useUploadDocument, useVerifyKyc,
} from "@/hooks/useTenants";
import { useBuildings } from "@/hooks/useBuildings";
import { useUnits } from "@/hooks/useUnits";
import { getErrorMessage } from "@/lib/apiError";
import { cn } from "@/lib/cn";
import { isNonNegativeAmountOrBlank, isPositiveAmount } from "@/lib/formValidators";
import type { KycStatus, TenantDetail } from "@/lib/types";
import { downloadCsv, downloadPdf } from "@/lib/downloadPdf";
import { avatarFor } from "@/lib/images";


const inputCls =
  "w-full rounded-md bg-surface-raised hairline px-3 py-2.5 text-sm text-ink-900 placeholder:text-ink-400 focus:outline-none focus:ring-2 focus:ring-sage-500/40";

function Field({
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
const KYC_TONE: Record<KycStatus, "paid" | "ochre" | "coral" | "neutral"> = {
  verified: "paid",
  pending: "ochre",
  rejected: "coral",
  not_started: "neutral",
};

function KycBadge({ status, label }: { status: KycStatus; label: string }) {
  return <Badge tone={KYC_TONE[status]} withDot>KYC: {label}</Badge>;
}

const KYC_DOC_TYPES = [
  { value: "id_front", label: "ID — Front" },
  { value: "id_back", label: "ID — Back" },
  { value: "passport", label: "Passport" },
  { value: "kra_pin_certificate", label: "KRA PIN Certificate" },
] as const;

function KycPanel({ tenant }: { tenant: TenantDetail }) {
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

// ─── Create Tenant Form ──────────────────────────────────────────────────────
const createSchema = z.object({
  first_name: z.string().min(1, "Required"),
  last_name: z.string().min(1, "Required"),
  id_number: z.string().min(1, "Required"),
  kra_pin: z.string().regex(/^[AP]\d{9}[A-Z]$/, "Format: A007523148T").or(z.literal("")).optional(),
  phone: z.string().min(1, "Required"),
  email: z.string().email().or(z.literal("")).optional(),
  emergency_contact: z.string().optional(),
  emergency_phone: z.string().optional(),
  unit: z.coerce.number().min(1, "Select a unit"),
  monthly_rent: z
    .string()
    .min(1, "Required")
    .refine(isPositiveAmount, "Enter an amount greater than 0"),
  deposit_paid: z
    .string()
    .optional()
    .refine(isNonNegativeAmountOrBlank, "Enter a valid amount"),
  due_day: z.coerce.number().int().min(1).max(31).optional(),
  move_in_date: z.string().min(1, "Required"),
  notes: z.string().optional(),
});
type CreateFormValues = z.infer<typeof createSchema>;

// ─── Edit / Notice / Move-out schemas ────────────────────────────────────────
const editSchema = z.object({
  first_name: z.string().min(1, "Required"),
  last_name: z.string().min(1, "Required"),
  kra_pin: z.string().regex(/^[AP]\d{9}[A-Z]$/, "Format: A007523148T").or(z.literal("")).optional(),
  phone: z.string().min(1, "Required"),
  email: z.string().email("Enter a valid email").or(z.literal("")).optional(),
  care_of: z.string().optional(),
  monthly_rent: z
    .string()
    .min(1, "Required")
    .refine(isPositiveAmount, "Enter an amount greater than 0"),
  deposit_paid: z
    .string()
    .optional()
    .refine(isNonNegativeAmountOrBlank, "Enter a valid amount"),
  due_day: z.coerce.number().int().min(1).max(31).optional(),
  deposit_refund_percentage: z.coerce
    .number({ invalid_type_error: "Enter a number between 0 and 100" })
    .min(0, "Cannot be below 0")
    .max(100, "Cannot exceed 100"),
  emergency_contact: z.string().optional(),
  emergency_phone: z.string().optional(),
  notes: z.string().optional(),
});
type EditFormValues = z.infer<typeof editSchema>;

const noticeSchema = z.object({
  notice_date: z.string().min(1, "Required"),
  intended_move_out_date: z.string().min(1, "Required"),
  notes: z.string().optional(),
});
type NoticeFormValues = z.infer<typeof noticeSchema>;

const moveOutSchema = z.object({
  move_out_date: z.string().min(1, "Required"),
  deposit_refund_percentage: z.coerce
    .number({ invalid_type_error: "Enter a number between 0 and 100" })
    .min(0, "Cannot be below 0")
    .max(100, "Cannot exceed 100"),
  notes: z.string().optional(),
});
type MoveOutFormValues = z.infer<typeof moveOutSchema>;

function CreateTenantForm({ onClose }: { onClose: () => void }) {
  const { data: vacantUnits } = useUnits({ status: "vacant" });
  const createTenant = useCreateTenant();
  const { register, handleSubmit, formState: { errors } } = useForm<CreateFormValues>({
    resolver: zodResolver(createSchema),
    defaultValues: { deposit_paid: "0", move_in_date: new Date().toISOString().slice(0, 10) },
  });
  const onSubmit = async (values: CreateFormValues) => {
    try {
      await createTenant.mutateAsync(values as unknown as Record<string, unknown>);
      toast.success("Tenant registered");
      onClose();
    } catch (e) { toast.error(getErrorMessage(e, "Failed to register tenant")); }
  };
  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Field label="First name *" error={errors.first_name?.message}>
          <input {...register("first_name")} className={inputCls} />
        </Field>
        <Field label="Last name *" error={errors.last_name?.message}>
          <input {...register("last_name")} className={inputCls} />
        </Field>
        <Field label="ID number *" error={errors.id_number?.message}>
          <input {...register("id_number")} className={inputCls} />
        </Field>
        <Field label="KRA PIN" error={errors.kra_pin?.message}>
          <input {...register("kra_pin")} className={inputCls} placeholder="A007523148T" />
        </Field>
        <Field label="Phone *" error={errors.phone?.message}>
          <input {...register("phone")} className={inputCls} placeholder="+254…" />
        </Field>
        <Field label="Email">
          <input type="email" {...register("email")} className={inputCls} />
        </Field>
        <Field label="Unit *" error={errors.unit?.message}>
          <select {...register("unit")} className={inputCls}>
            <option value={0}>Select a vacant unit…</option>
            {vacantUnits?.map((u) => (
              <option key={u.id} value={u.id}>
                {u.building_name} — {u.label} (KES {Number(u.monthly_rent).toLocaleString()})
              </option>
            ))}
          </select>
        </Field>
        <Field label="Monthly rent (KES) *" error={errors.monthly_rent?.message}>
          <input {...register("monthly_rent")} className={inputCls} />
        </Field>
        <Field label="Deposit paid (KES)">
          <input {...register("deposit_paid")} className={inputCls} />
        </Field>
        <Field label="Rent Due Day (1-31)" error={errors.due_day?.message}>
          <input type="number" min={1} max={31} {...register("due_day")} className={inputCls} />
        </Field>

        <DatePicker label="Move-in date *" {...register("move_in_date")} error={errors.move_in_date?.message} />
        <Field label="Emergency contact">
          <input {...register("emergency_contact")} className={inputCls} />
        </Field>
        <Field label="Emergency phone">
          <input {...register("emergency_phone")} className={inputCls} />
        </Field>
      </div>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
        <Button type="submit" loading={createTenant.isPending}>
          <Plus className="h-4 w-4" /> Register & move in
        </Button>
      </div>
    </form>
  );
}

// ─── Tenant Detail Modal ─────────────────────────────────────────────────────
function TenantDetailModal({ tenantId, onClose }: { tenantId: number; onClose: () => void }) {
  const { data: tenant, isLoading, isError, refetch } = useTenant(tenantId);
  const updateTenant = useUpdateTenant(tenantId);
  const moveOutNotice = useMoveOutNotice(tenantId);
  const moveOut = useMoveOutTenant(tenantId);
  const [mode, setMode] = useState<"view" | "edit" | "notice" | "moveout">("view");

  const editForm = useForm<EditFormValues>({ resolver: zodResolver(editSchema) });
  const noticeForm = useForm<NoticeFormValues>({
    resolver: zodResolver(noticeSchema),
    defaultValues: { notice_date: new Date().toISOString().slice(0, 10), intended_move_out_date: "", notes: "" },
  });
  const moveOutForm = useForm<MoveOutFormValues>({
    resolver: zodResolver(moveOutSchema),
    defaultValues: { move_out_date: new Date().toISOString().slice(0, 10), deposit_refund_percentage: 100, notes: "" },
  });

  const handleDownloadStatement = async () => {
    try {
      await downloadPdf(`/tenants/${tenantId}/statement-pdf/`, `wilkem-statement-${tenantId}.pdf`);
    } catch {
      toast.error("Failed to download statement");
    }
  };


  useEffect(() => {
    if (tenant) {
      editForm.reset({
        first_name: tenant.first_name, last_name: tenant.last_name,
        kra_pin: tenant.kra_pin ?? "",
        phone: tenant.phone, email: tenant.email ?? "",
        care_of: tenant.care_of ?? "",
        monthly_rent: String(tenant.monthly_rent),
        deposit_paid: String(tenant.deposit_paid),
        deposit_refund_percentage: tenant.deposit_refund_percentage ?? 100,
        emergency_contact: tenant.emergency_contact ?? "",
        emergency_phone: tenant.emergency_phone ?? "",
        due_day: tenant.due_day ?? 5,
        notes: tenant.notes ?? "",

      });
    }
  }, [tenant, editForm]);


  const isActive = tenant?.status === "active" || tenant?.status === "notice_given";

  const headerActions = (
    <>
      {isActive && mode === "view" && (
        <>
          <Button size="sm" variant="glass" onClick={() => setMode("edit")}><Pencil className="h-3.5 w-3.5" /> Edit</Button>
          <Button size="sm" variant="glass" onClick={handleDownloadStatement}><FileText className="h-3.5 w-3.5" /> Statement PDF</Button>
          <Button size="sm" variant="glass" onClick={() => setMode("notice")}><AlertTriangle className="h-3.5 w-3.5" /> Notice</Button>
          <Button size="sm" variant="danger" onClick={() => setMode("moveout")}><LogOut className="h-3.5 w-3.5" /> Move Out</Button>
        </>
      )}
      {mode !== "view" && <Button size="sm" variant="ghost" onClick={() => setMode("view")}>Cancel</Button>}
    </>
  );

  return (
    <Modal
      open
      onClose={onClose}
      size="lg"
      eyebrow={tenant ? `${tenant.building_name} · ${tenant.unit_label}` : undefined}
      title={isLoading ? "Loading…" : tenant?.full_name}
      headerActions={headerActions}
    >
        <div className="space-y-5">
          {isLoading && <div className="space-y-3">{Array.from({length:4}).map((_,i) => <div key={i} className="h-8 rounded bg-ink-100 animate-pulse" />)}</div>}
          {isError && !tenant && (
            <ErrorState
              title="This tenant could not be loaded."
              description="The record did not come back. This is usually temporary."
              onRetry={() => void refetch()}
            />
          )}
          {tenant && mode === "view" && (
            <>
              <div className="flex items-center gap-4">
                <img src={avatarFor(tenant.full_name)} alt="" className="h-14 w-14 rounded-full shadow" />
                <div>
                  <p className="font-display text-xl font-semibold text-ink-900">{tenant.full_name}</p>
                  <p className="text-sm text-ink-500">{tenant.building_name} — {tenant.unit_label}</p>
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    <Badge tone={tenant.status === "active" ? "sage" : tenant.status === "notice_given" ? "ochre" : "neutral"} withDot>
                      {tenant.status_display}
                    </Badge>
                    <KycBadge status={tenant.kyc_status} label={tenant.kyc_status_display} />
                  </div>
                </div>
              </div>
              <div className="grid gap-2 sm:grid-cols-2 text-sm">
                {([
                  ["Phone", tenant.phone],
                  ["Email", tenant.email || "—"],
                  ["ID Number", tenant.id_number],
                  ["Emergency Contact", tenant.emergency_contact || "—"],
                  ["Move-in Date", tenant.move_in_date],
                  ["Move-out Date", tenant.move_out_date || "Active"],
                  ["Monthly Rent", `KES ${Number(tenant.monthly_rent).toLocaleString()}`],
                  ["Deposit Paid", `KES ${Number(tenant.deposit_paid).toLocaleString()}`],
                  ["Deposit Refund %", `${tenant.deposit_refund_percentage ?? 100}%`],
                  ...(tenant.deposit_refund_amount != null ? [["Deposit Refund Amount", `KES ${Number(tenant.deposit_refund_amount).toLocaleString()}`]] : []),
                  ...(tenant.due_day ? [["Rent Due Day", String(tenant.due_day)]] : []),
                  ...(tenant.notice_date ? [["Notice Given", tenant.notice_date]] : []),

                  ...(tenant.intended_move_out_date ? [["Intended Move-out", tenant.intended_move_out_date]] : []),
                ] as [string, string][]).map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-2 rounded-md bg-ink-50 px-3 py-2 dark:bg-ink-800">
                    <span className="text-ink-500">{k}</span>
                    <span className="font-medium text-ink-900 dark:text-white">{v}</span>
                  </div>
                ))}
              </div>
              <div className="rounded-md bg-sage-500/8 p-4">
                <p className="text-[11px] font-medium uppercase tracking-wider text-ink-500 mb-3">Payment Analytics</p>
                <div className="grid grid-cols-2 gap-3">
                  <div className="rounded-md bg-white p-3 text-center dark:bg-ink-800">
                    <p className="font-display text-xl font-semibold text-sage-700">KES {(tenant.total_paid ?? 0).toLocaleString()}</p>
                    <p className="text-[11px] text-ink-500">Total paid</p>
                  </div>
                  <div className="rounded-md bg-white p-3 text-center dark:bg-ink-800">
                    <p className={`font-display text-xl font-semibold ${(tenant.total_arrears ?? 0) > 0 ? "text-status-unpaid" : "text-sage-700"}`}>
                      KES {(tenant.total_arrears ?? 0).toLocaleString()}
                    </p>
                    <p className="text-[11px] text-ink-500">Arrears</p>
                  </div>
                </div>
              </div>
              <KycPanel tenant={tenant} />
            </>
          )}
          {tenant && mode === "edit" && (
            <form onSubmit={editForm.handleSubmit(async (v) => {
              try { await updateTenant.mutateAsync(v as unknown as Record<string, unknown>); toast.success("Updated"); setMode("view"); }
              catch (e) { toast.error(getErrorMessage(e, "Failed to update tenant")); }
            })} className="space-y-4">
              <p className="font-medium text-ink-900">Edit Tenant Details</p>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="First name" error={editForm.formState.errors.first_name?.message}><input {...editForm.register("first_name")} className={inputCls} /></Field>
                <Field label="Last name" error={editForm.formState.errors.last_name?.message}><input {...editForm.register("last_name")} className={inputCls} /></Field>
                <Field label="KRA PIN" error={editForm.formState.errors.kra_pin?.message}><input {...editForm.register("kra_pin")} className={inputCls} placeholder="A007523148T" /></Field>
                <Field label="Phone" error={editForm.formState.errors.phone?.message}><input {...editForm.register("phone")} className={inputCls} /></Field>
                <Field label="Email" error={editForm.formState.errors.email?.message}><input {...editForm.register("email")} className={inputCls} /></Field>
                <Field label="Monthly rent (KES)" error={editForm.formState.errors.monthly_rent?.message}><input {...editForm.register("monthly_rent")} className={inputCls} /></Field>
                <Field label="Deposit paid (KES)"><input {...editForm.register("deposit_paid")} className={inputCls} /></Field>
                <Field label="Rent Due Day (1-31)" error={editForm.formState.errors.due_day?.message}><input type="number" min={1} max={31} {...editForm.register("due_day")} className={inputCls} /></Field>

                <Field label="Deposit refund % (for move-out)" error={editForm.formState.errors.deposit_refund_percentage?.message}>
                  <input type="number" min={0} max={100} {...editForm.register("deposit_refund_percentage")} className={inputCls} />
                </Field>
                <Field label="Emergency contact"><input {...editForm.register("emergency_contact")} className={inputCls} /></Field>
                <Field label="Emergency phone"><input {...editForm.register("emergency_phone")} className={inputCls} /></Field>
                <Field label="c/o (appears on rent statement)">
                  <input {...editForm.register("care_of")} className={inputCls} placeholder="e.g. David Chibeka" />
                </Field>
              </div>
              <div className="flex justify-end gap-2">
                <Button type="button" variant="ghost" onClick={() => setMode("view")}>Cancel</Button>
                <Button type="submit" loading={updateTenant.isPending}>Save changes</Button>
              </div>
            </form>
          )}
          {tenant && mode === "notice" && (
            <form onSubmit={noticeForm.handleSubmit(async (v) => {
              try { await moveOutNotice.mutateAsync({ notice_date: v.notice_date, intended_move_out_date: v.intended_move_out_date, notes: v.notes }); toast.success("Notice recorded"); setMode("view"); }
              catch (e) { toast.error(getErrorMessage(e, "Failed to record notice")); }
            })} className="space-y-4">
              <p className="font-medium text-ink-900">Record Move-out Notice</p>
              <div className="grid gap-3 sm:grid-cols-2">
                <DatePicker label="Notice date *" {...noticeForm.register("notice_date")} error={noticeForm.formState.errors.notice_date?.message} />
                <DatePicker label="Intended move-out date *" {...noticeForm.register("intended_move_out_date")} error={noticeForm.formState.errors.intended_move_out_date?.message} />
              </div>
              <Field label="Notes"><textarea {...noticeForm.register("notes")} rows={2} className={inputCls} /></Field>
              <div className="flex justify-end gap-2">
                <Button type="button" variant="ghost" onClick={() => setMode("view")}>Cancel</Button>
                <Button type="submit" loading={moveOutNotice.isPending}>Record notice</Button>
              </div>
            </form>
          )}
          {tenant && mode === "moveout" && (
            <form onSubmit={moveOutForm.handleSubmit(async (v) => {
              try {
                await moveOut.mutateAsync({ move_out_date: v.move_out_date, notes: v.notes, deposit_refund_percentage: v.deposit_refund_percentage });
                toast.success("Tenant moved out"); onClose();
              } catch (e) { toast.error(getErrorMessage(e, "Failed to process move-out")); }
            })} className="space-y-4">
              <div className="rounded-md bg-status-unpaid/8 p-3 text-sm text-status-unpaid flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 shrink-0" />
                This will move the tenant out and free up the unit.
              </div>
              <DatePicker label="Move-out date *" {...moveOutForm.register("move_out_date")} error={moveOutForm.formState.errors.move_out_date?.message} />
              <Field label="Deposit refund %" error={moveOutForm.formState.errors.deposit_refund_percentage?.message}>
                <input type="number" min={0} max={100} step={1} {...moveOutForm.register("deposit_refund_percentage")} className={inputCls} />
              </Field>
              <p className="-mt-2 text-[11px] text-ink-500">
                Deposit paid: KES {Number(tenant.deposit_paid).toLocaleString()}. Set to 0% if all forfeited due to damage.
              </p>
              <Field label="Notes"><textarea {...moveOutForm.register("notes")} rows={2} className={inputCls} /></Field>
              <div className="flex justify-end gap-2">
                <Button type="button" variant="ghost" onClick={() => setMode("view")}>Cancel</Button>
                <Button type="submit" variant="danger" loading={moveOut.isPending}><LogOut className="h-4 w-4" /> Confirm move-out</Button>
              </div>
            </form>
          )}
        </div>
    </Modal>
  );
}

// ─── Main Page ───────────────────────────────────────────────────────────────
export default function TenantsPage() {
  const [searchParams] = useSearchParams();
  const [statusFilter, setStatusFilter] = useState("");
  const [kycFilter, setKycFilter] = useState("");
  const [buildingFilter, setBuildingFilter] = useState<number | "">("");
  // Seed the paid/arrears filter from the URL so the dashboard's Arrears tile
  // drills straight into the in-arrears list.
  const [payFilter, setPayFilter] = useState(searchParams.get("payment_status") ?? "");
  const [search, setSearch] = useState(searchParams.get("q") ?? "");
  const [showForm, setShowForm] = useState(searchParams.get("new") === "1");
  const [selectedTenantId, setSelectedTenantId] = useState<number | null>(null);
  const [exporting, setExporting] = useState(false);

  useEffect(() => { setSearch(searchParams.get("q") ?? ""); }, [searchParams]);
  useEffect(() => { setPayFilter(searchParams.get("payment_status") ?? ""); }, [searchParams]);

  const filters: Record<string, string | number> = {};
  if (statusFilter) filters.status = statusFilter;
  if (kycFilter) filters.kyc_status = kycFilter;
  if (buildingFilter) filters.building = buildingFilter;
  if (payFilter) filters.payment_status = payFilter;
  if (search) filters.search = search;

  async function handleExport() {
    setExporting(true);
    try {
      await downloadCsv("/tenants/export/", "tenants.csv", filters);
    } catch {
      toast.error("Could not export the tenant list.");
    } finally {
      setExporting(false);
    }
  }

  const { data: tenants, isLoading, isError, refetch } = useTenants(filters);
  const { data: buildings } = useBuildings();

  // Build building filter tabs from actual buildings
  const buildingTabs = useMemo(() => [
    { id: "" as "" | number, name: "All" },
    ...(buildings ?? []).map((b) => ({ id: b.id as "" | number, name: b.name })),
  ], [buildings]);

  const STATUSES = [
    { value: "", label: "All" },
    { value: "active", label: "Active" },
    { value: "notice_given", label: "Notice Given" },
    { value: "moved_out", label: "Moved Out" },
  ];

  const PAY_FILTERS = [
    { value: "", label: "All" },
    { value: "paid", label: "Paid" },
    { value: "in_arrears", label: "In Arrears" },
  ];

  const KYC_FILTERS = [
    { value: "", label: "All KYC" },
    { value: "not_started", label: "Not Started" },
    { value: "pending", label: "Pending Review" },
    { value: "verified", label: "Verified" },
    { value: "rejected", label: "Rejected" },
  ];

  const pendingKycCount = tenants?.filter((t) => t.kyc_status === "pending").length ?? 0;

  const activeCount = tenants?.filter((t) => t.status === "active").length ?? 0;

  return (
    <>
      <div className="space-y-6">
        <PageHeader
          eyebrow="People"
          title="Tenants"
          description={`${activeCount} active · ${tenants?.length ?? 0} total on file${pendingKycCount > 0 ? ` · ${pendingKycCount} pending KYC` : ""}.`}
          actions={
            <div className="flex items-center gap-2">
              <Button
                variant="glass"
                onClick={handleExport}
                disabled={exporting || !tenants?.length}
              >
                <Download className="h-4 w-4" />
                {exporting ? "Exporting…" : "Export CSV"}
              </Button>
              <Button onClick={() => setShowForm(!showForm)}>
                {showForm ? <X className="h-4 w-4" /> : <UserPlus className="h-4 w-4" />}
                {showForm ? "Cancel" : "Register Tenant"}
              </Button>
            </div>
          }
        />

        {showForm && (
          <Card variant="glass" padding="md" className="animate-fade-up">
            <p className="mb-4 font-display text-lg font-semibold text-ink-900">New tenant</p>
            <CreateTenantForm onClose={() => setShowForm(false)} />
          </Card>
        )}

        {/* Search + filters */}
        <div className="flex flex-col gap-3">
          <Input leftIcon={<Search className="h-4 w-4" />} placeholder="Search by name, ID, phone…" value={search} onChange={(e) => setSearch(e.target.value)} />
          {/* Building tabs */}
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter by building">
            {buildingTabs.map((b) => (
              <button key={String(b.id)} onClick={() => setBuildingFilter(b.id as "" | number)}
                aria-pressed={buildingFilter === b.id}
                className={cn("rounded-full px-3 py-1.5 text-xs font-medium transition-all",
                  buildingFilter === b.id ? "bg-ink-900 text-canvas shadow-float" : "glass text-ink-700")}>
                {b.name}
              </button>
            ))}
          </div>
          {/* Status tabs */}
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter by status">
            {STATUSES.map((s) => (
              <button key={s.value} onClick={() => setStatusFilter(s.value)}
                aria-pressed={statusFilter === s.value}
                className={cn("rounded-full px-3 py-1.5 text-xs font-medium transition-all",
                  statusFilter === s.value ? "bg-ochre-500 text-ink-900 shadow-float" : "glass text-ink-700")}>
                {s.label}
              </button>
            ))}
          </div>
          {/* Payment status toggle */}
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter by payment status">
            {PAY_FILTERS.map((s) => (
              <button key={s.value} onClick={() => setPayFilter(s.value)}
                aria-pressed={payFilter === s.value}
                className={cn("rounded-full px-3 py-1.5 text-xs font-medium transition-all",
                  payFilter === s.value
                    ? s.value === "in_arrears"
                      ? "bg-coral-500 text-white shadow-float"
                      : "bg-sage-500 text-white shadow-float"
                    : "glass text-ink-700")}>
                {s.label}
              </button>
            ))}
          </div>
          {/* KYC tabs */}
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter by KYC status">
            {KYC_FILTERS.map((s) => (
              <button key={s.value} onClick={() => setKycFilter(s.value)}
                aria-pressed={kycFilter === s.value}
                className={cn("flex items-center gap-1 rounded-full px-3 py-1.5 text-xs font-medium transition-all",
                  kycFilter === s.value ? "bg-ink-900 text-canvas shadow-float" : "glass text-ink-700")}>
                {s.value === "pending" && <ShieldCheck className="h-3 w-3" />}
                {s.label}
                {s.value === "pending" && pendingKycCount > 0 && (
                  <span className="ml-0.5 rounded-full bg-ochre-500 px-1.5 text-[10px] font-semibold text-ink-900">{pendingKycCount}</span>
                )}
              </button>
            ))}
          </div>
        </div>

        {isLoading ? (
          <div className="space-y-2">{Array.from({length:5}).map((_,i) => <Skeleton key={i} className="h-14" />)}</div>
        ) : isError ? (
          <ErrorState
            title="Tenants could not be loaded."
            description="The tenant list did not come back. This is usually temporary."
            onRetry={() => void refetch()}
          />
        ) : !tenants?.length ? (
          <EmptyState icon={<UserPlus className="h-5 w-5" />} title="No tenants found" description="Try a different filter or register your first tenant." />
        ) : (
          <>
            {/* Desktop table */}
            <div className="hidden md:block">
              <Table>
                <THead>
                  <TR>
                    <TH>Tenant</TH>
                    <TH>Building</TH>
                    <TH>Unit</TH>
                    <TH>Phone</TH>
                    <TH className="text-right">Rent (KES)</TH>
                    <TH className="text-right">Balance (KES)</TH>
                    <TH>Move-in</TH>
                    <TH>Status</TH>
                    <TH>KYC</TH>
                  </TR>
                </THead>
                <TBody>
                  {tenants.map((t) => (
                    <TR
                      key={t.id}
                      className="cursor-pointer hover:bg-ink-50/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ochre-500/40 dark:hover:bg-ink-800/30"
                      role="button"
                      tabIndex={0}
                      aria-label={`View ${t.full_name}`}
                      onClick={() => setSelectedTenantId(t.id)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          setSelectedTenantId(t.id);
                        }
                      }}
                    >
                      <TD>
                        <div className="flex items-center gap-3">
                          <img src={avatarFor(t.full_name)} alt="" aria-hidden className="h-9 w-9 rounded-full" />
                          <p className="truncate font-medium text-ink-900">{t.full_name}</p>
                        </div>
                      </TD>
                      <TD className="text-ink-500">{t.building_name}</TD>
                      <TD>{t.unit_label}</TD>
                      <TD className="font-mono text-xs">{t.phone}</TD>
                      <TD className="text-right font-medium tabular-nums">{Number(t.monthly_rent).toLocaleString()}</TD>
                      <TD className="text-right tabular-nums">
                        <span className={cn("font-medium", t.payment_status === "in_arrears" ? "text-coral-600" : "text-sage-600")}>
                          {Number(t.balance).toLocaleString()}
                        </span>
                      </TD>
                      <TD className="text-ink-500">{t.move_in_date}</TD>
                      <TD>
                        <Badge tone={t.status === "active" ? "sage" : t.status === "notice_given" ? "ochre" : "neutral"} withDot>
                          {t.status_display}
                        </Badge>
                      </TD>
                      <TD>
                        <Badge tone={KYC_TONE[t.kyc_status]} withDot>{t.kyc_status_display}</Badge>
                      </TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            </div>
            {/* Mobile cards */}
            <div className="grid gap-3 md:hidden">
              {tenants.map((t) => (
                <Card
                  key={t.id}
                  variant="glass"
                  padding="sm"
                  className="cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ochre-500/40"
                  role="button"
                  tabIndex={0}
                  aria-label={`View ${t.full_name}`}
                  onClick={() => setSelectedTenantId(t.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      setSelectedTenantId(t.id);
                    }
                  }}
                >
                  <div className="flex items-start gap-3">
                    <img src={avatarFor(t.full_name)} alt="" aria-hidden className="h-10 w-10 rounded-full" />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <p className="truncate font-medium text-ink-900">{t.full_name}</p>
                          <p className="truncate text-[11px] text-ink-500">{t.building_name} · {t.unit_label}</p>
                        </div>
                        <div className="flex flex-col items-end gap-1">
                          <Badge tone={t.status === "active" ? "sage" : t.status === "notice_given" ? "ochre" : "neutral"} withDot>{t.status_display}</Badge>
                          <Badge tone={KYC_TONE[t.kyc_status]} withDot>{t.kyc_status_display}</Badge>
                        </div>
                      </div>
                      <div className="mt-2 flex items-center justify-between text-xs">
                        <a href={`tel:${t.phone}`} onClick={(e) => e.stopPropagation()} className="flex items-center gap-1 text-sage-600">
                          <Phone className="h-3 w-3" />{t.phone}
                        </a>
                        <p className={cn("font-medium tabular-nums", t.payment_status === "in_arrears" ? "text-coral-600" : "text-ink-900")}>
                          {t.payment_status === "in_arrears" ? `KES ${Number(t.balance).toLocaleString()} due` : "Paid up"}
                        </p>
                      </div>
                    </div>
                  </div>
                </Card>
              ))}
            </div>
          </>
        )}
      </div>

      {selectedTenantId && (
        <TenantDetailModal tenantId={selectedTenantId} onClose={() => setSelectedTenantId(null)} />
      )}
    </>
  );
}
