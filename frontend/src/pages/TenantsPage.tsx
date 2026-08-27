/**
 * TenantsPage — tenant roster.
 * - Building / status / payment / KYC filters
 * - Rows and mobile cards navigate to the full tenant detail page (/tenants/:id)
 * - Per-tenant "Remind" (SMS / Email) for anyone in arrears
 */
import { zodResolver } from "@hookform/resolvers/zod";
import {
  BellRing, ChevronDown, Download, Phone, Plus, Search, UserPlus, X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import toast from "react-hot-toast";
import { useNavigate, useSearchParams } from "react-router-dom";
import { z } from "zod";

import {
  Badge, Button, Card, DatePicker, EmptyState, ErrorState, Input,
  PageHeader, Skeleton, Table, TBody, TD, TH, THead, TR,
} from "@/components/ui";
import { Field, inputCls, KYC_TONE, RemindModal } from "@/features/tenants/shared";
import { useBuildings } from "@/hooks/useBuildings";
import { useCreateTenant, useTenants } from "@/hooks/useTenants";
import { useUnits } from "@/hooks/useUnits";
import { getErrorMessage } from "@/lib/apiError";
import { cn } from "@/lib/cn";
import { downloadCsv } from "@/lib/downloadPdf";
import { isNonNegativeAmountOrBlank, isPositiveAmount } from "@/lib/formValidators";
import { avatarFor } from "@/lib/images";
import type { TenantListItem } from "@/lib/types";

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
        <Field label="Rent security deposit (KES)">
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

// ─── Filter dropdown ─────────────────────────────────────────────────────────
function FilterSelect({
  label, value, onChange, options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <div className="relative">
      <select
        aria-label={label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={cn(
          "h-full w-full appearance-none rounded-md border border-border bg-surface py-2.5 pl-3.5 pr-9 text-sm transition-colors",
          "focus:border-teal-600 focus:outline-none focus:ring-2 focus:ring-ring/25",
          value ? "font-medium text-content" : "text-content-muted",
        )}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
      <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-content-muted" />
    </div>
  );
}

// ─── Main Page ───────────────────────────────────────────────────────────────
export default function TenantsPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [statusFilter, setStatusFilter] = useState("");
  const [kycFilter, setKycFilter] = useState("");
  const [buildingFilter, setBuildingFilter] = useState<number | "">("");
  // Seed the paid/arrears filter from the URL so the dashboard's Arrears tile
  // drills straight into the in-arrears list.
  const [payFilter, setPayFilter] = useState(searchParams.get("payment_status") ?? "");
  const [search, setSearch] = useState(searchParams.get("q") ?? "");
  const [showForm, setShowForm] = useState(searchParams.get("new") === "1");
  const [remindTenant, setRemindTenant] = useState<TenantListItem | null>(null);
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
    { id: "" as "" | number, name: "All buildings" },
    ...(buildings ?? []).map((b) => ({ id: b.id as "" | number, name: b.name })),
  ], [buildings]);

  const STATUSES = [
    { value: "", label: "All statuses" },
    { value: "active", label: "Active" },
    { value: "notice_given", label: "Notice Given" },
    { value: "moved_out", label: "Moved Out" },
  ];

  const PAY_FILTERS = [
    { value: "", label: "All payments" },
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

  const openTenant = (id: number) => navigate(`/tenants/${id}`);

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
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
          <Input
            className="lg:flex-1"
            leftIcon={<Search className="h-4 w-4" />}
            placeholder="Search by name, ID, phone…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:flex lg:flex-wrap">
            <FilterSelect
              label="Filter by building"
              value={String(buildingFilter)}
              onChange={(v) => setBuildingFilter(v === "" ? "" : Number(v))}
              options={buildingTabs.map((b) => ({ value: String(b.id), label: b.name }))}
            />
            <FilterSelect
              label="Filter by status"
              value={statusFilter}
              onChange={setStatusFilter}
              options={STATUSES}
            />
            <FilterSelect
              label="Filter by payment status"
              value={payFilter}
              onChange={setPayFilter}
              options={PAY_FILTERS}
            />
            <FilterSelect
              label="Filter by KYC status"
              value={kycFilter}
              onChange={setKycFilter}
              options={KYC_FILTERS.map((s) => ({
                value: s.value,
                label: s.value === "pending" && pendingKycCount > 0
                  ? `${s.label} (${pendingKycCount})`
                  : s.label,
              }))}
            />
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
                    <TH className="text-right">Actions</TH>
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
                      onClick={() => openTenant(t.id)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          openTenant(t.id);
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
                      <TD className="text-right">
                        {t.payment_status === "in_arrears" && t.status !== "moved_out" ? (
                          <Button
                            size="sm"
                            variant="glass"
                            aria-label={`Send rent reminder to ${t.full_name}`}
                            onClick={(e) => {
                              e.stopPropagation();
                              setRemindTenant(t);
                            }}
                          >
                            <BellRing className="h-3.5 w-3.5" /> Remind
                          </Button>
                        ) : (
                          <span className="text-ink-300">—</span>
                        )}
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
                  className="min-w-0 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ochre-500/40"
                  role="button"
                  tabIndex={0}
                  aria-label={`View ${t.full_name}`}
                  onClick={() => openTenant(t.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      openTenant(t.id);
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
                      {t.payment_status === "in_arrears" && t.status !== "moved_out" && (
                        <div className="mt-2 flex justify-end">
                          <Button
                            size="sm"
                            variant="glass"
                            aria-label={`Send rent reminder to ${t.full_name}`}
                            onClick={(e) => {
                              e.stopPropagation();
                              setRemindTenant(t);
                            }}
                          >
                            <BellRing className="h-3.5 w-3.5" /> Remind
                          </Button>
                        </div>
                      )}
                    </div>
                  </div>
                </Card>
              ))}
            </div>
          </>
        )}
      </div>

      {remindTenant && (
        <RemindModal tenant={remindTenant} onClose={() => setRemindTenant(null)} />
      )}
    </>
  );
}
