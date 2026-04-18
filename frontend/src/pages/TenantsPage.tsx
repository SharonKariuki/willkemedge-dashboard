import { zodResolver } from "@hookform/resolvers/zod";
import { Phone, Plus, Search, UserPlus, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import toast from "react-hot-toast";
import { useSearchParams } from "react-router-dom";
import { z } from "zod";

import {
  Badge,
  Button,
  Card,
  EmptyState,
  Input,
  PageHeader,
  Skeleton,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "@/components/ui";
import { useCreateTenant, useTenants } from "@/hooks/useTenants";
import { useUnits } from "@/hooks/useUnits";
import { cn } from "@/lib/cn";
import { avatarFor } from "@/lib/images";

const TENANT_STATUSES = [
  { value: "", label: "All" },
  { value: "active", label: "Active" },
  { value: "moved_out", label: "Moved Out" },
];

const schema = z.object({
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
  move_in_date: z.string().min(1, "Required"),
  notes: z.string().optional(),
});

type FormValues = z.infer<typeof schema>;

const inputCls =
  "w-full rounded-md bg-surface-raised hairline px-3 py-2.5 text-sm text-ink-900 placeholder:text-ink-400 focus:outline-none focus:ring-2 focus:ring-sage-500/40";

function Field({
  label,
  error,
  children,
  className,
}: {
  label: string;
  error?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={className}>
      <label className="mb-1 block text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">
        {label}
      </label>
      {children}
      {error && <p className="mt-1 text-[11px] text-status-unpaid">{error}</p>}
    </div>
  );
}

export default function TenantsPage() {
  const [searchParams] = useSearchParams();
  const [statusFilter, setStatusFilter] = useState("");
  const [search, setSearch] = useState(searchParams.get("q") ?? "");
  const [showForm, setShowForm] = useState(false);

  useEffect(() => {
    const q = searchParams.get("q") ?? "";
    setSearch(q);
  }, [searchParams]);

  const filters: Record<string, string> = {};
  if (statusFilter) filters.status = statusFilter;
  if (search) filters.search = search;

  const { data: tenants, isLoading } = useTenants(filters);
  const { data: vacantUnits } = useUnits({ status: "vacant" });
  const createTenant = useCreateTenant();

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      first_name: "",
      last_name: "",
      id_number: "",
      phone: "",
      email: "",
      unit: 0,
      monthly_rent: "",
      deposit_paid: "0",
      move_in_date: new Date().toISOString().slice(0, 10),
    },
  });

  const onSubmit = async (values: FormValues) => {
    try {
      await createTenant.mutateAsync(values);
      toast.success("Tenant registered and moved in");
      reset();
      setShowForm(false);
    } catch {
      toast.error("Failed to register tenant");
    }
  };

  const activeCount = tenants?.filter((t) => t.status === "active").length ?? 0;

  return (
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

      {/* Add tenant form */}
      {showForm && (
        <Card variant="glass" padding="md" className="animate-fade-up">
          <div className="mb-5">
            <p className="font-display text-lg font-semibold text-ink-900">New tenant</p>
            <p className="text-xs text-ink-500">
              Fill in the details below to register and move in a new tenant.
            </p>
          </div>
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
              <Field label="Move-in date *" error={errors.move_in_date?.message}>
                <input type="date" {...register("move_in_date")} className={inputCls} />
              </Field>
              <Field label="Emergency contact">
                <input {...register("emergency_contact")} className={inputCls} />
              </Field>
              <Field label="Emergency phone">
                <input {...register("emergency_phone")} className={inputCls} />
              </Field>
            </div>
            <div className="flex justify-end">
              <Button type="submit" loading={createTenant.isPending}>
                <Plus className="h-4 w-4" />
                Register & move in
              </Button>
            </div>
          </form>
        </Card>
      )}

      {/* Filters */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="flex-1">
          <Input
            leftIcon={<Search className="h-4 w-4" />}
            placeholder="Search by name, ID, phone…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="flex flex-wrap gap-1.5">
          {TENANT_STATUSES.map((s) => {
            const active = statusFilter === s.value;
            return (
              <button
                key={s.value || "all"}
                onClick={() => setStatusFilter(s.value)}
                className={cn(
                  "rounded-full px-3 py-1.5 text-xs font-medium transition-all",
                  active
                    ? "bg-ink-900 text-canvas shadow-float dark:bg-ink-100 dark:text-canvas"
                    : "glass text-ink-700"
                )}
              >
                {s.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Tenants — table on md+, cards below */}
      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-14" />
          ))}
        </div>
      ) : !tenants?.length ? (
        <EmptyState
          icon={<UserPlus className="h-5 w-5" />}
          title="No tenants yet"
          description="Register your first tenant to get started."
        />
      ) : (
        <>
          <div className="hidden md:block">
            <Table>
              <THead>
                <TR>
                  <TH>Tenant</TH>
                  <TH>Unit</TH>
                  <TH>Phone</TH>
                  <TH className="text-right">Rent (KES)</TH>
                  <TH>Move-in</TH>
                  <TH>Status</TH>
                </TR>
              </THead>
              <TBody>
                {tenants.map((t) => (
                  <TR key={t.id}>
                    <TD>
                      <div className="flex items-center gap-3">
                        <img
                          src={avatarFor(t.full_name)}
                          alt=""
                          aria-hidden
                          className="h-9 w-9 rounded-full"
                        />
                        <div className="min-w-0">
                          <p className="truncate font-medium text-ink-900">{t.full_name}</p>
                          <p className="truncate text-[11px] text-ink-500">
                            {t.building_name}
                          </p>
                        </div>
                      </div>
                    </TD>
                    <TD>{t.unit_label}</TD>
                    <TD className="font-mono text-xs">{t.phone}</TD>
                    <TD className="text-right font-medium tabular-nums">
                      {Number(t.monthly_rent).toLocaleString()}
                    </TD>
                    <TD className="text-ink-500">{t.move_in_date}</TD>
                    <TD>
                      <Badge tone={t.status === "active" ? "sage" : "neutral"} withDot>
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
              <Card key={t.id} variant="glass" padding="sm">
                <div className="flex items-start gap-3">
                  <img src={avatarFor(t.full_name)} alt="" aria-hidden className="h-10 w-10 rounded-full" />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate font-medium text-ink-900">{t.full_name}</p>
                        <p className="truncate text-[11px] text-ink-500">
                          {t.building_name} · {t.unit_label}
                        </p>
                      </div>
                      <Badge tone={t.status === "active" ? "sage" : "neutral"} withDot>
                        {t.status_display}
                      </Badge>
                    </div>
                    <div className="mt-2 flex items-center justify-between text-xs">
                      <a
                        href={`tel:${t.phone}`}
                        className="flex items-center gap-1 text-sage-600 dark:text-sage-400"
                      >
                        <Phone className="h-3 w-3" />
                        {t.phone}
                      </a>
                      <p className="font-medium text-ink-900 tabular-nums">
                        KES {Number(t.monthly_rent).toLocaleString()}
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
  );
}
