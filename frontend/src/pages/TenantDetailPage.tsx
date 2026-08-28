/**
 * TenantDetailPage — /tenants/:id
 *
 * The bottom of the Property → Unit → Tenant drill-down, and (since we replaced
 * the tenant modal) the single place to manage a tenant: contact info, payment
 * history + arrears, the downloadable statement, KYC, edit / notice / move-out,
 * and a rent reminder (SMS / Email).
 */
import { zodResolver } from "@hookform/resolvers/zod";
import { AlertTriangle, ArrowLeft, BellRing, Download, LogOut, Mail, Pencil, Phone } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import toast from "react-hot-toast";
import { useNavigate, useParams } from "react-router-dom";
import { z } from "zod";

import {
  Badge, Button, Card, DatePicker, ErrorState, Skeleton,
  Table, TBody, TD, TH, THead, TR,
} from "@/components/ui";
import { Field, KycPanel, RemindModal, inputCls } from "@/features/tenants/shared";
import {
  usePaymentHistory, useMoveOutNotice, useMoveOutTenant, useTenant, useUpdateTenant,
} from "@/hooks/useTenants";
import { getErrorMessage } from "@/lib/apiError";
import { cn } from "@/lib/cn";
import { downloadPdf } from "@/lib/downloadPdf";
import { isNonNegativeAmountOrBlank, isPositiveAmount } from "@/lib/formValidators";

const KES = (n: string | number) => `KES ${Number(n || 0).toLocaleString()}`;

// ─── Edit / Notice / Move-out schemas ────────────────────────────────────────
const editSchema = z.object({
  first_name: z.string().min(1, "Required"),
  last_name: z.string().min(1, "Required"),
  kra_pin: z.string().regex(/^[AP]\d{9}[A-Z]$/, "Format: A007523148T").or(z.literal("")).optional(),
  phone: z.string().min(1, "Required"),
  email: z.string().email("Enter a valid email").or(z.literal("")).optional(),
  care_of: z.string().optional(),
  monthly_rent: z.string().min(1, "Required").refine(isPositiveAmount, "Enter an amount greater than 0"),
  deposit_paid: z.string().optional().refine(isNonNegativeAmountOrBlank, "Enter a valid amount"),
  due_day: z.coerce.number().int().min(1).max(31).optional(),
  deposit_refund_percentage: z.coerce
    .number({ invalid_type_error: "Enter a number between 0 and 100" })
    .min(0, "Cannot be below 0").max(100, "Cannot exceed 100"),
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
    .min(0, "Cannot be below 0").max(100, "Cannot exceed 100"),
  notes: z.string().optional(),
});
type MoveOutFormValues = z.infer<typeof moveOutSchema>;

type Mode = "view" | "edit" | "notice" | "moveout";

export default function TenantDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { data: tenant, isLoading, isError, refetch } = useTenant(id ?? null);
  const { data: history } = usePaymentHistory(id ?? null);
  // Commercial units carry 16% VAT and the statement bills it as its own
  // column; residential is exempt. Drive it off the ledger rather than the
  // unit's classification so a unit reclassified mid-tenancy still shows the
  // VAT it was actually charged.
  const showVat = (history?.monthly_ledger ?? []).some((m) => Number(m.vat) > 0);
  const updateTenant = useUpdateTenant(id ?? "");
  const moveOutNotice = useMoveOutNotice(id ?? "");
  const moveOut = useMoveOutTenant(id ?? "");

  const [mode, setMode] = useState<Mode>("view");
  const [reminding, setReminding] = useState(false);
  const [downloading, setDownloading] = useState(false);

  const editForm = useForm<EditFormValues>({ resolver: zodResolver(editSchema) });
  const noticeForm = useForm<NoticeFormValues>({
    resolver: zodResolver(noticeSchema),
    defaultValues: { notice_date: new Date().toISOString().slice(0, 10), intended_move_out_date: "", notes: "" },
  });
  const moveOutForm = useForm<MoveOutFormValues>({
    resolver: zodResolver(moveOutSchema),
    defaultValues: { move_out_date: new Date().toISOString().slice(0, 10), deposit_refund_percentage: 100, notes: "" },
  });

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

  async function handleStatement() {
    setDownloading(true);
    try {
      await downloadPdf(`/tenants/${id}/statement-pdf/`, `Statement-${tenant?.full_name ?? id}.pdf`);
    } catch (e) {
      toast.error(getErrorMessage(e, "Could not download the statement."));
    } finally {
      setDownloading(false);
    }
  }

  if (isLoading) {
    return <div className="space-y-4">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-24" />)}</div>;
  }
  if (isError || !tenant) {
    return (
      <ErrorState
        title="Tenant could not be loaded."
        description="This is usually temporary."
        onRetry={() => void refetch()}
      />
    );
  }

  const isActive = tenant.status === "active" || tenant.status === "notice_given";
  const inArrears = tenant.payment_status === "in_arrears";

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <button
            onClick={() => navigate(-1)}
            className="mb-2 inline-flex items-center gap-1 text-sm text-content-muted hover:text-content"
          >
            <ArrowLeft className="h-4 w-4" /> Back
          </button>
          <h1 className="font-display text-2xl font-bold text-content sm:text-3xl">{tenant.full_name}</h1>
          <p className="mt-1 text-sm text-content-muted">
            {tenant.building_name} · Unit {tenant.unit_label}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {isActive && mode === "view" && (
            <>
              {inArrears && (
                <Button variant="outline" onClick={() => setReminding(true)}>
                  <BellRing className="h-4 w-4" /> Remind
                </Button>
              )}
              <Button variant="outline" onClick={() => setMode("edit")}><Pencil className="h-4 w-4" /> Edit</Button>
              <Button variant="outline" onClick={handleStatement} loading={downloading}>
                <Download className="h-4 w-4" /> Statement PDF
              </Button>
              <Button variant="outline" onClick={() => setMode("notice")}><AlertTriangle className="h-4 w-4" /> Notice</Button>
              <Button variant="danger" onClick={() => setMode("moveout")}><LogOut className="h-4 w-4" /> Move Out</Button>
            </>
          )}
          {!isActive && mode === "view" && (
            <Button variant="outline" onClick={handleStatement} loading={downloading}>
              <Download className="h-4 w-4" /> Statement PDF
            </Button>
          )}
          {mode !== "view" && (
            <Button variant="ghost" onClick={() => setMode("view")}>Cancel</Button>
          )}
        </div>
      </div>

      {/* Edit / Notice / Move-out forms */}
      {mode === "edit" && (
        <Card padding="md">
          <form onSubmit={editForm.handleSubmit(async (v) => {
            try { await updateTenant.mutateAsync(v as unknown as Record<string, unknown>); toast.success("Updated"); setMode("view"); }
            catch (e) { toast.error(getErrorMessage(e, "Failed to update tenant")); }
          })} className="space-y-4">
            <p className="font-semibold text-content">Edit tenant details</p>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              <Field label="First name" error={editForm.formState.errors.first_name?.message}><input {...editForm.register("first_name")} className={inputCls} /></Field>
              <Field label="Last name" error={editForm.formState.errors.last_name?.message}><input {...editForm.register("last_name")} className={inputCls} /></Field>
              <Field label="KRA PIN" error={editForm.formState.errors.kra_pin?.message}><input {...editForm.register("kra_pin")} className={inputCls} placeholder="A007523148T" /></Field>
              <Field label="Phone" error={editForm.formState.errors.phone?.message}><input {...editForm.register("phone")} className={inputCls} /></Field>
              <Field label="Email" error={editForm.formState.errors.email?.message}><input {...editForm.register("email")} className={inputCls} /></Field>
              <Field label="Monthly rent (KES)" error={editForm.formState.errors.monthly_rent?.message}><input {...editForm.register("monthly_rent")} className={inputCls} /></Field>
              <Field label="Rent security deposit (KES)"><input {...editForm.register("deposit_paid")} className={inputCls} /></Field>
              <Field label="Rent Due Day (1-31)" error={editForm.formState.errors.due_day?.message}><input type="number" min={1} max={31} {...editForm.register("due_day")} className={inputCls} /></Field>
              <Field label="Deposit refund % (for move-out)" error={editForm.formState.errors.deposit_refund_percentage?.message}>
                <input type="number" min={0} max={100} {...editForm.register("deposit_refund_percentage")} className={inputCls} />
              </Field>
              <Field label="Emergency contact"><input {...editForm.register("emergency_contact")} className={inputCls} /></Field>
              <Field label="Emergency phone"><input {...editForm.register("emergency_phone")} className={inputCls} /></Field>
              <Field label="c/o (appears on rent statement)"><input {...editForm.register("care_of")} className={inputCls} placeholder="e.g. David Chibeka" /></Field>
            </div>
            <div className="flex justify-end gap-2">
              <Button type="button" variant="ghost" onClick={() => setMode("view")}>Cancel</Button>
              <Button type="submit" loading={updateTenant.isPending}>Save changes</Button>
            </div>
          </form>
        </Card>
      )}

      {mode === "notice" && (
        <Card padding="md">
          <form onSubmit={noticeForm.handleSubmit(async (v) => {
            try { await moveOutNotice.mutateAsync({ notice_date: v.notice_date, intended_move_out_date: v.intended_move_out_date, notes: v.notes }); toast.success("Notice recorded"); setMode("view"); }
            catch (e) { toast.error(getErrorMessage(e, "Failed to record notice")); }
          })} className="space-y-4">
            <p className="font-semibold text-content">Record move-out notice</p>
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
        </Card>
      )}

      {mode === "moveout" && (
        <Card padding="md">
          <form onSubmit={moveOutForm.handleSubmit(async (v) => {
            try {
              await moveOut.mutateAsync({ move_out_date: v.move_out_date, notes: v.notes, deposit_refund_percentage: v.deposit_refund_percentage });
              toast.success("Tenant moved out"); setMode("view");
            } catch (e) { toast.error(getErrorMessage(e, "Failed to process move-out")); }
          })} className="space-y-4">
            <div className="rounded-md bg-status-unpaid/8 p-3 text-sm text-status-unpaid flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              This will move the tenant out and free up the unit.
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <DatePicker label="Move-out date *" {...moveOutForm.register("move_out_date")} error={moveOutForm.formState.errors.move_out_date?.message} />
              <Field label="Deposit refund %" error={moveOutForm.formState.errors.deposit_refund_percentage?.message}>
                <input type="number" min={0} max={100} step={1} {...moveOutForm.register("deposit_refund_percentage")} className={inputCls} />
              </Field>
            </div>
            <p className="-mt-1 text-[11px] text-content-muted">
              Deposit paid: {KES(tenant.deposit_paid)}. Set to 0% if all forfeited due to damage.
            </p>
            <Field label="Notes"><textarea {...moveOutForm.register("notes")} rows={2} className={inputCls} /></Field>
            <div className="flex justify-end gap-2">
              <Button type="button" variant="ghost" onClick={() => setMode("view")}>Cancel</Button>
              <Button type="submit" variant="danger" loading={moveOut.isPending}><LogOut className="h-4 w-4" /> Confirm move-out</Button>
            </div>
          </form>
        </Card>
      )}

      {/* Contact + finance summary */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card padding="md">
          <p className="text-xs uppercase tracking-wider text-content-muted">Status</p>
          <div className="mt-2">
            <Badge tone={tenant.status === "active" ? "sage" : tenant.status === "notice_given" ? "ochre" : "neutral"} withDot>
              {tenant.status_display}
            </Badge>
          </div>
        </Card>
        <Card padding="md">
          <p className="text-xs uppercase tracking-wider text-content-muted">Monthly rent</p>
          <p className="mt-2 font-semibold tabular-nums text-content">{KES(tenant.monthly_rent)}</p>
        </Card>
        <Card padding="md">
          <p className="text-xs uppercase tracking-wider text-content-muted">Rent security deposit</p>
          <p className="mt-2 font-semibold tabular-nums text-content">{KES(tenant.deposit_paid)}</p>
        </Card>
        <Card padding="md">
          <p className="text-xs uppercase tracking-wider text-content-muted">Arrears</p>
          <p className={cn("mt-2 font-semibold tabular-nums", inArrears ? "text-orange-600" : "text-sage-600")}>
            {KES(history?.total_arrears ?? 0)}
          </p>
        </Card>
      </div>

      {/* Contact */}
      <Card padding="md">
        <p className="mb-3 font-semibold text-content">Contact</p>
        <div className="flex flex-wrap gap-6 text-sm">
          <a href={`tel:${tenant.phone}`} className="inline-flex items-center gap-2 text-sage-600">
            <Phone className="h-4 w-4" /> {tenant.phone}
          </a>
          {tenant.email && (
            <a href={`mailto:${tenant.email}`} className="inline-flex items-center gap-2 text-sage-600">
              <Mail className="h-4 w-4" /> {tenant.email}
            </a>
          )}
          {tenant.id_number && <span className="text-content-muted">ID: {tenant.id_number}</span>}
          {tenant.kra_pin && <span className="text-content-muted">KRA: {tenant.kra_pin}</span>}
        </div>
      </Card>

      {/* KYC */}
      <KycPanel tenant={tenant} />

      {/* Payment history */}
      <Card padding="none">
        <div className="border-b border-hairline px-5 py-4">
          <h2 className="font-semibold text-content">Payment history</h2>
        </div>
        {history?.payments.length ? (
          <Table>
            <THead>
              <TR><TH>Date</TH><TH>Period</TH><TH>Method</TH><TH>Reference</TH><TH className="text-right">Amount</TH></TR>
            </THead>
            <TBody>
              {history.payments.map((p) => (
                <TR key={p.id}>
                  <TD className="text-content-muted">{p.payment_date}</TD>
                  <TD>{p.period_month}/{p.period_year}</TD>
                  <TD><Badge tone="neutral">{p.source || "—"}</Badge></TD>
                  <TD className="font-mono text-xs text-content-muted">{p.reference || "—"}</TD>
                  <TD className="text-right font-medium tabular-nums text-content">{KES(p.amount)}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        ) : (
          <p className="px-5 py-6 text-sm text-content-muted">No payments recorded yet.</p>
        )}
      </Card>

      {/* Monthly rent roll — one row per month, extends itself as billing posts.
          VAT gets its own column for commercial units, matching the statement;
          residential is exempt, so the column is hidden rather than showing a
          row of dashes. */}
      <Card padding="none">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-hairline px-5 py-4">
          <h2 className="font-semibold text-content">Monthly rent roll</h2>
          <p className="text-xs text-content-muted">
            Arrears b/f + rent + other charges − payments. A new row appears each month.
          </p>
        </div>
        {history?.monthly_ledger?.length ? (
          <Table>
            <THead>
              <TR>
                <TH>Month</TH>
                <TH className="text-right">Arrears b/f</TH>
                <TH className="text-right">Rent</TH>
                {showVat && <TH className="text-right">16% VAT</TH>}
                <TH className="text-right">Other charges</TH>
                <TH className="text-right">Total due</TH>
                <TH className="text-right">Payment made</TH>
                <TH className="text-right">Balance</TH>
              </TR>
            </THead>
            <TBody>
              {history.monthly_ledger.map((m) => {
                const balance = Number(m.balance);
                return (
                  <TR key={m.period}>
                    <TD className="whitespace-nowrap">{m.label}</TD>
                    <TD className="text-right tabular-nums text-content-muted">{KES(m.brought_forward)}</TD>
                    <TD className="text-right tabular-nums">{KES(m.rent)}</TD>
                    {showVat && (
                      <TD className="text-right tabular-nums text-content-muted">
                        {Number(m.vat) ? KES(m.vat) : "—"}
                      </TD>
                    )}
                    <TD className="text-right tabular-nums text-content-muted">
                      {Number(m.other_charges) ? KES(m.other_charges) : "—"}
                    </TD>
                    <TD className="text-right tabular-nums">{KES(m.total_due)}</TD>
                    <TD className="text-right tabular-nums text-sage-600">{KES(m.paid)}</TD>
                    <TD className={cn(
                      "text-right font-medium tabular-nums",
                      balance > 0 ? "text-orange-600" : "text-sage-600",
                    )}>
                      {balance < 0 ? `${KES(Math.abs(balance))} cr` : KES(balance)}
                    </TD>
                  </TR>
                );
              })}
            </TBody>
          </Table>
        ) : (
          <p className="px-5 py-6 text-sm text-content-muted">
            Nothing billed yet — the first row appears once rent is charged for a month.
          </p>
        )}
      </Card>

      {reminding && <RemindModal tenant={tenant} onClose={() => setReminding(false)} />}
    </div>
  );
}
