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
  AlertTriangle, FileText, LogOut,
  Pencil, Phone, Plus, Search, UserPlus, X,
} from "lucide-react";


import { useEffect, useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import toast from "react-hot-toast";
import { useSearchParams } from "react-router-dom";
import { z } from "zod";

import {
  Badge, Button, Card, DatePicker, EmptyState, Input,
  PageHeader, Skeleton, Table, TBody, TD, TH, THead, TR,
} from "@/components/ui";
import {
  useCreateTenant, useMoveOutNotice, useMoveOutTenant,
  useTenant, useTenants, useUpdateTenant,
} from "@/hooks/useTenants";
import { useBuildings } from "@/hooks/useBuildings";
import { useUnits } from "@/hooks/useUnits";
import { cn } from "@/lib/cn";
import { avatarFor } from "@/lib/images";


const inputCls =
  "w-full rounded-md bg-surface-raised hairline px-3 py-2.5 text-sm text-ink-900 placeholder:text-ink-400 focus:outline-none focus:ring-2 focus:ring-sage-500/40";

function Field({
  label, error, children, className,
}: { label: string; error?: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={className}>
      <label className="mb-1 block text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">{label}</label>
      {children}
      {error && <p className="mt-1 text-[11px] text-status-unpaid">{error}</p>}
    </div>
  );
}

// ─── Create Tenant Form ──────────────────────────────────────────────────────
const createSchema = z.object({
  first_name: z.string().min(1, "Required"),
  last_name: z.string().min(1, "Required"),
  id_number: z.string().min(1, "Required"),
  phone: z.string().min(1, "Required"),
  email: z.string().email().or(z.literal("")).optional(),
  emergency_contact: z.string().optional(),
  emergency_phone: z.string().optional(),
  unit: z.coerce.number().min(1, "Select a unit"),
  monthly_rent: z.string().min(1, "Required"),
  deposit_paid: z.string().optional(),
  due_day: z.coerce.number().int().min(1).max(31).default(5),
  move_in_date: z.string().min(1, "Required"),

  notes: z.string().optional(),
});
type CreateFormValues = z.infer<typeof createSchema>;

function CreateTenantForm({ onClose }: { onClose: () => void }) {
  const { data: vacantUnits } = useUnits({ status: "vacant" });
  const createTenant = useCreateTenant();
  const { register, handleSubmit, formState: { errors } } = useForm<CreateFormValues>({
    resolver: zodResolver(createSchema),
    defaultValues: { deposit_paid: "0", move_in_date: new Date().toISOString().slice(0, 10) },
  });
  const onSubmit = async (values: CreateFormValues) => {
    try {
      await createTenant.mutateAsync(values as Record<string, unknown>);
      toast.success("Tenant registered");
      onClose();
    } catch { toast.error("Failed to register tenant"); }
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
  const { data: tenant, isLoading } = useTenant(tenantId);
  const updateTenant = useUpdateTenant(tenantId);
  const moveOutNotice = useMoveOutNotice(tenantId);
  const moveOut = useMoveOutTenant(tenantId);
  const [mode, setMode] = useState<"view" | "edit" | "notice" | "moveout">("view");

  const editForm = useForm();
  const noticeForm = useForm({
    defaultValues: { notice_date: new Date().toISOString().slice(0, 10), intended_move_out_date: "", notes: "" },
  });
  const moveOutForm = useForm({
    defaultValues: { move_out_date: new Date().toISOString().slice(0, 10), deposit_refund_percentage: "100", notes: "" },
  });

  const handleDownloadStatement = () => {
    const baseUrl = import.meta.env.VITE_API_URL || "http://localhost:8000";
    window.open(`${baseUrl}/api/tenants/${tenantId}/statement-pdf/`, "_blank");
  };


  useEffect(() => {
    if (tenant) {
      editForm.reset({
        first_name: tenant.first_name, last_name: tenant.last_name,
        phone: tenant.phone, email: tenant.email ?? "",
        monthly_rent: String(tenant.monthly_rent),
        deposit_paid: String(tenant.deposit_paid),
        deposit_refund_percentage: String(tenant.deposit_refund_percentage ?? "100"),
        emergency_contact: tenant.emergency_contact ?? "",
        emergency_phone: tenant.emergency_phone ?? "",
        due_day: tenant.due_day ?? 5,
        notes: tenant.notes ?? "",

      });
    }
  }, [tenant, editForm]);


  const isActive = tenant?.status === "active" || tenant?.status === "notice_given";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-ink-900/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-xl bg-white shadow-float dark:bg-ink-900 animate-fade-up">
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-ink-100 bg-white px-6 py-4 dark:border-ink-700 dark:bg-ink-900">
          <p className="font-display text-lg font-semibold text-ink-900 dark:text-white">
            {isLoading ? "Loading…" : tenant?.full_name}
          </p>
          <div className="flex items-center gap-2">
            {isActive && mode === "view" && (
              <>
                <Button size="sm" variant="glass" onClick={() => setMode("edit")}><Pencil className="h-3.5 w-3.5" /> Edit</Button>
                <Button size="sm" variant="glass" onClick={handleDownloadStatement}><FileText className="h-3.5 w-3.5" /> Statement PDF</Button>
                <Button size="sm" variant="glass" onClick={() => setMode("notice")}><AlertTriangle className="h-3.5 w-3.5" /> Notice</Button>
                <Button size="sm" variant="danger" onClick={() => setMode("moveout")}><LogOut className="h-3.5 w-3.5" /> Move Out</Button>
              </>
            )}

            {mode !== "view" && <Button size="sm" variant="ghost" onClick={() => setMode("view")}>Cancel</Button>}
            <button onClick={onClose} className="rounded-md p-1.5 text-ink-400 hover:text-ink-700"><X className="h-4 w-4" /></button>
          </div>
        </div>
        <div className="p-6 space-y-5">
          {isLoading && <div className="space-y-3">{Array.from({length:4}).map((_,i) => <div key={i} className="h-8 rounded bg-ink-100 animate-pulse" />)}</div>}
          {tenant && mode === "view" && (
            <>
              <div className="flex items-center gap-4">
                <img src={avatarFor(tenant.full_name)} alt="" className="h-14 w-14 rounded-full shadow" />
                <div>
                  <p className="font-display text-xl font-semibold text-ink-900">{tenant.full_name}</p>
                  <p className="text-sm text-ink-500">{tenant.building_name} — {tenant.unit_label}</p>
                  <Badge tone={tenant.status === "active" ? "sage" : tenant.status === "notice_given" ? "ochre" : "neutral"} withDot className="mt-1">
                    {tenant.status_display}
                  </Badge>
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
                    <p className="font-display text-xl font-semibold text-sage-700">KES {((tenant as Record<string,unknown>).total_paid as number ?? 0).toLocaleString()}</p>
                    <p className="text-[11px] text-ink-500">Total paid</p>
                  </div>
                  <div className="rounded-md bg-white p-3 text-center dark:bg-ink-800">
                    <p className={`font-display text-xl font-semibold ${((tenant as Record<string,unknown>).total_arrears as number ?? 0) > 0 ? "text-status-unpaid" : "text-sage-700"}`}>
                      KES {((tenant as Record<string,unknown>).total_arrears as number ?? 0).toLocaleString()}
                    </p>
                    <p className="text-[11px] text-ink-500">Arrears</p>
                  </div>
                </div>
              </div>
            </>
          )}
          {tenant && mode === "edit" && (
            <form onSubmit={editForm.handleSubmit(async (v) => {
              try { await updateTenant.mutateAsync(v); toast.success("Updated"); setMode("view"); }
              catch { toast.error("Failed to update"); }
            })} className="space-y-4">
              <p className="font-medium text-ink-900">Edit Tenant Details</p>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="First name"><input {...editForm.register("first_name")} className={inputCls} /></Field>
                <Field label="Last name"><input {...editForm.register("last_name")} className={inputCls} /></Field>
                <Field label="Phone"><input {...editForm.register("phone")} className={inputCls} /></Field>
                <Field label="Email"><input {...editForm.register("email")} className={inputCls} /></Field>
                <Field label="Monthly rent (KES)"><input {...editForm.register("monthly_rent")} className={inputCls} /></Field>
                <Field label="Deposit paid (KES)"><input {...editForm.register("deposit_paid")} className={inputCls} /></Field>
                <Field label="Rent Due Day (1-31)"><input type="number" min={1} max={31} {...editForm.register("due_day")} className={inputCls} /></Field>

                <Field label="Deposit refund % (for move-out)">
                  <input type="number" min={0} max={100} {...editForm.register("deposit_refund_percentage")} className={inputCls} />
                </Field>
                <Field label="Emergency contact"><input {...editForm.register("emergency_contact")} className={inputCls} /></Field>
                <Field label="Emergency phone"><input {...editForm.register("emergency_phone")} className={inputCls} /></Field>
              </div>
              <div className="flex justify-end gap-2">
                <Button type="button" variant="ghost" onClick={() => setMode("view")}>Cancel</Button>
                <Button type="submit" loading={updateTenant.isPending}>Save changes</Button>
              </div>
            </form>
          )}
          {tenant && mode === "notice" && (
            <form onSubmit={noticeForm.handleSubmit(async (v) => {
              try { await moveOutNotice.mutateAsync(v as { notice_date: string; intended_move_out_date: string; notes?: string }); toast.success("Notice recorded"); setMode("view"); }
              catch { toast.error("Failed"); }
            })} className="space-y-4">
              <p className="font-medium text-ink-900">Record Move-out Notice</p>
              <div className="grid gap-3 sm:grid-cols-2">
                <DatePicker label="Notice date *" {...noticeForm.register("notice_date")} />
                <DatePicker label="Intended move-out date *" {...noticeForm.register("intended_move_out_date")} />
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
                await moveOut.mutateAsync({ move_out_date: v.move_out_date, notes: v.notes, deposit_refund_percentage: Number(v.deposit_refund_percentage) });
                toast.success("Tenant moved out"); onClose();
              } catch { toast.error("Failed to process move-out"); }
            })} className="space-y-4">
              <div className="rounded-md bg-status-unpaid/8 p-3 text-sm text-status-unpaid flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 shrink-0" />
                This will move the tenant out and free up the unit.
              </div>
              <DatePicker label="Move-out date *" {...moveOutForm.register("move_out_date")} />
              <Field label="Deposit refund %">
                <input type="number" min={0} max={100} step={1} {...moveOutForm.register("deposit_refund_percentage")} className={inputCls} />
                <p className="mt-1 text-[11px] text-ink-500">
                  Deposit paid: KES {Number(tenant.deposit_paid).toLocaleString()}. Set to 0% if all forfeited due to damage.
                </p>
              </Field>
              <Field label="Notes"><textarea {...moveOutForm.register("notes")} rows={2} className={inputCls} /></Field>
              <div className="flex justify-end gap-2">
                <Button type="button" variant="ghost" onClick={() => setMode("view")}>Cancel</Button>
                <Button type="submit" variant="danger" loading={moveOut.isPending}><LogOut className="h-4 w-4" /> Confirm move-out</Button>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Main Page ───────────────────────────────────────────────────────────────
export default function TenantsPage() {
  const [searchParams] = useSearchParams();
  const [statusFilter, setStatusFilter] = useState("");
  const [buildingFilter, setBuildingFilter] = useState<number | "">("");
  const [search, setSearch] = useState(searchParams.get("q") ?? "");
  const [showForm, setShowForm] = useState(false);
  const [selectedTenantId, setSelectedTenantId] = useState<number | null>(null);

  useEffect(() => { setSearch(searchParams.get("q") ?? ""); }, [searchParams]);

  const filters: Record<string, string | number> = {};
  if (statusFilter) filters.status = statusFilter;
  if (buildingFilter) filters.building = buildingFilter;
  if (search) filters.search = search;

  const { data: tenants, isLoading } = useTenants(filters);
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

  const activeCount = tenants?.filter((t) => t.status === "active").length ?? 0;

  return (
    <>
      <div className="space-y-6">
        <PageHeader
          eyebrow="People"
          title="Tenants"
          description={`${activeCount} active · ${tenants?.length ?? 0} total on file.`}
          actions={
            <Button onClick={() => setShowForm(!showForm)}>
              {showForm ? <X className="h-4 w-4" /> : <UserPlus className="h-4 w-4" />}
              {showForm ? "Cancel" : "Register Tenant"}
            </Button>
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
          <div className="flex flex-wrap gap-1.5">
            {buildingTabs.map((b) => (
              <button key={String(b.id)} onClick={() => setBuildingFilter(b.id as "" | number)}
                className={cn("rounded-full px-3 py-1.5 text-xs font-medium transition-all",
                  buildingFilter === b.id ? "bg-ink-900 text-canvas shadow-float" : "glass text-ink-700")}>
                {b.name}
              </button>
            ))}
          </div>
          {/* Status tabs */}
          <div className="flex flex-wrap gap-1.5">
            {STATUSES.map((s) => (
              <button key={s.value} onClick={() => setStatusFilter(s.value)}
                className={cn("rounded-full px-3 py-1.5 text-xs font-medium transition-all",
                  statusFilter === s.value ? "bg-ochre-500 text-ink-900 shadow-float" : "glass text-ink-700")}>
                {s.label}
              </button>
            ))}
          </div>
        </div>

        {isLoading ? (
          <div className="space-y-2">{Array.from({length:5}).map((_,i) => <Skeleton key={i} className="h-14" />)}</div>
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
                    <TH>Deposit (KES)</TH>
                    <TH>Move-in</TH>
                    <TH>Status</TH>
                  </TR>
                </THead>
                <TBody>
                  {tenants.map((t) => (
                    <TR key={t.id} className="cursor-pointer hover:bg-ink-50/60 dark:hover:bg-ink-800/30" onClick={() => setSelectedTenantId(t.id)}>
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
                      <TD className="tabular-nums">{Number(t.deposit_paid).toLocaleString()}</TD>
                      <TD className="text-ink-500">{t.move_in_date}</TD>
                      <TD>
                        <Badge tone={t.status === "active" ? "sage" : t.status === "notice_given" ? "ochre" : "neutral"} withDot>
                          {t.status_display}
                        </Badge>
                      </TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            </div>
            {/* Mobile cards */}
            <div className="grid gap-3 md:hidden">
              {tenants.map((t) => (
                <Card key={t.id} variant="glass" padding="sm" className="cursor-pointer" onClick={() => setSelectedTenantId(t.id)}>
                  <div className="flex items-start gap-3">
                    <img src={avatarFor(t.full_name)} alt="" aria-hidden className="h-10 w-10 rounded-full" />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <p className="truncate font-medium text-ink-900">{t.full_name}</p>
                          <p className="truncate text-[11px] text-ink-500">{t.building_name} · {t.unit_label}</p>
                        </div>
                        <Badge tone={t.status === "active" ? "sage" : t.status === "notice_given" ? "ochre" : "neutral"} withDot>{t.status_display}</Badge>
                      </div>
                      <div className="mt-2 flex items-center justify-between text-xs">
                        <a href={`tel:${t.phone}`} onClick={(e) => e.stopPropagation()} className="flex items-center gap-1 text-sage-600">
                          <Phone className="h-3 w-3" />{t.phone}
                        </a>
                        <p className="font-medium text-ink-900 tabular-nums">KES {Number(t.monthly_rent).toLocaleString()}</p>
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
