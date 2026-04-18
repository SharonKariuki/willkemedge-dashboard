import { zodResolver } from "@hookform/resolvers/zod";
import { Banknote, Building2, CreditCard, Plus, Smartphone, Sparkles, UserPlus, Wallet, X } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import toast from "react-hot-toast";
import { Link } from "react-router-dom";
import { z } from "zod";

import ProgressBar from "@/components/ProgressBar";
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
  useCollectionProgress,
  useCreatePayment,
  useMockPayment,
  usePayments,
} from "@/hooks/usePayments";
import { useTenants } from "@/hooks/useTenants";
import { cn } from "@/lib/cn";
import { avatarFor } from "@/lib/images";

const SOURCES = [
  { value: "", label: "All" },
  { value: "cash", label: "Cash" },
  { value: "mpesa", label: "M-Pesa" },
  { value: "bank", label: "Bank" },
  { value: "cheque", label: "Cheque" },
];

const now = new Date();

const schema = z.object({
  tenant: z.coerce.number().min(1, "Select a tenant"),
  amount: z.string().min(1, "Required"),
  payment_date: z.string().min(1, "Required"),
  period_month: z.coerce.number().min(1).max(12),
  period_year: z.coerce.number().min(2020),
  source: z.string().min(1),
  reference: z.string().optional(),
  notes: z.string().optional(),
});

type FormValues = z.infer<typeof schema>;

const inputCls =
  "w-full rounded-md bg-surface-raised hairline px-3 py-2.5 text-sm text-ink-900 placeholder:text-ink-400 focus:outline-none focus:ring-2 focus:ring-sage-500/40";

const SOURCE_CONFIG: Record<string, { tone: "sage" | "peri" | "ochre" | "coral"; icon: React.ComponentType<{ className?: string }> }> = {
  mpesa: { tone: "sage", icon: Smartphone },
  bank: { tone: "peri", icon: Building2 },
  cash: { tone: "ochre", icon: Banknote },
  cheque: { tone: "peri", icon: Wallet },
};

function SourceChip({ source, label }: { source: string; label: string }) {
  const config = SOURCE_CONFIG[source] ?? { tone: "sage" as const, icon: Wallet };
  const Icon = config.icon;
  return (
    <Badge tone={config.tone}>
      <Icon className="h-3 w-3" />
      {label}
    </Badge>
  );
}

function Field({
  label,
  error,
  children,
}: {
  label: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="mb-1 block text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">
        {label}
      </label>
      {children}
      {error && <p className="mt-1 text-[11px] text-status-unpaid">{error}</p>}
    </div>
  );
}

interface MockTenant {
  id: number;
  full_name: string;
  unit_label: string;
  monthly_rent: string;
}

function MockPaymentPanel({
  tenants,
  tenantsLoading,
  isPending,
  onSubmit,
}: {
  tenants: MockTenant[];
  tenantsLoading: boolean;
  isPending: boolean;
  onSubmit: (payload: { tenant: number; amount: string; source: "mpesa" | "bank" | "cash" }) => Promise<void>;
}) {
  const [tenantId, setTenantId] = useState<number>(tenants[0]?.id ?? 0);
  const [amount, setAmount] = useState<string>("");
  const [source, setSource] = useState<"mpesa" | "bank" | "cash">("mpesa");

  const selectedTenant = tenants.find((t) => t.id === Number(tenantId));
  const effectiveAmount = amount || selectedTenant?.monthly_rent || "";

  const submit = async () => {
    if (!tenantId) {
      toast.error("Select a tenant");
      return;
    }
    const numericAmount = Number(effectiveAmount);
    if (!numericAmount || numericAmount <= 0) {
      toast.error("Enter a valid amount");
      return;
    }
    await onSubmit({ tenant: tenantId, amount: String(numericAmount), source });
  };

  const SOURCE_OPTIONS: { value: "mpesa" | "bank" | "cash"; label: string; icon: React.ComponentType<{ className?: string }>; desc: string }[] = [
    { value: "mpesa", label: "M-Pesa", icon: Smartphone, desc: "Generates a TransID like MP1234ABCD" },
    { value: "bank", label: "Bank", icon: Building2, desc: "Generates a bank reference BK1234ABCD" },
    { value: "cash", label: "Cash", icon: Banknote, desc: "Cash paid at the office" },
  ];

  return (
    <Card variant="glass" padding="md" className="animate-fade-up">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <p className="font-display text-lg font-semibold text-ink-900">Simulate a payment</p>
          <p className="text-xs text-ink-500">
            Generates a realistic mock payment from M-Pesa, a bank transfer, or cash — including
            reference number and full arrears/unit-status processing.
          </p>
        </div>
        <Badge tone="ochre">
          <Sparkles className="h-3 w-3" />
          Demo
        </Badge>
      </div>

      <div className="mb-4 grid gap-2 sm:grid-cols-3">
        {SOURCE_OPTIONS.map((opt) => {
          const Icon = opt.icon;
          const active = source === opt.value;
          return (
            <button
              key={opt.value}
              type="button"
              onClick={() => setSource(opt.value)}
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

      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Tenant *">
          <select
            value={tenantId || 0}
            onChange={(e) => setTenantId(Number(e.target.value))}
            className={inputCls}
            disabled={tenantsLoading}
          >
            <option value={0}>
              {tenantsLoading ? "Loading…" : "Select tenant…"}
            </option>
            {tenants.map((t) => (
              <option key={t.id} value={t.id}>
                {t.full_name} ({t.unit_label})
              </option>
            ))}
          </select>
        </Field>
        <Field label={`Amount (KES)${selectedTenant ? ` — rent KES ${Number(selectedTenant.monthly_rent).toLocaleString()}` : ""}`}>
          <input
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            placeholder={selectedTenant?.monthly_rent ?? "e.g. 15000"}
            className={inputCls}
          />
        </Field>
        <div className="flex items-end">
          <Button onClick={submit} loading={isPending} className="w-full">
            <CreditCard className="h-4 w-4" />
            Simulate {source.toUpperCase()}
          </Button>
        </div>
      </div>
    </Card>
  );
}

export default function PaymentsPage() {
  const [sourceFilter, setSourceFilter] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [showMock, setShowMock] = useState(false);

  const filters: Record<string, string> = {};
  if (sourceFilter) filters.source = sourceFilter;

  const { data: payments, isLoading } = usePayments(filters);
  const { data: progress } = useCollectionProgress();
  const { data: tenants, isLoading: tenantsLoading } = useTenants({ status: "active" });
  const createPayment = useCreatePayment();
  const mockPayment = useMockPayment();

  const hasTenants = (tenants?.length ?? 0) > 0;

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      tenant: 0,
      amount: "",
      payment_date: now.toISOString().slice(0, 10),
      period_month: now.getMonth() + 1,
      period_year: now.getFullYear(),
      source: "cash",
      reference: "",
      notes: "",
    },
  });

  const onSubmit = async (values: FormValues) => {
    try {
      await createPayment.mutateAsync(values);
      toast.success("Payment recorded");
      reset();
      setShowForm(false);
    } catch {
      toast.error("Failed to record payment");
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Collections"
        title="Payments"
        description="Record rent payments and track monthly collection progress."
        actions={
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              onClick={() => {
                setShowMock((v) => !v);
                if (!showMock) setShowForm(false);
              }}
            >
              {showMock ? <X className="h-4 w-4" /> : <Sparkles className="h-4 w-4" />}
              {showMock ? "Cancel" : "Simulate Payment"}
            </Button>
            <Button
              variant="gold"
              onClick={() => {
                setShowForm((v) => !v);
                if (!showForm) setShowMock(false);
              }}
            >
              {showForm ? <X className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
              {showForm ? "Cancel" : "Record Payment"}
            </Button>
          </div>
        }
      />

      {showMock && (
        <MockPaymentPanel
          tenants={tenants ?? []}
          tenantsLoading={tenantsLoading}
          isPending={mockPayment.isPending}
          onSubmit={async (payload) => {
            try {
              await mockPayment.mutateAsync(payload);
              toast.success(`Mock ${payload.source.toUpperCase()} payment recorded`);
              setShowMock(false);
            } catch {
              toast.error("Failed to simulate payment");
            }
          }}
        />
      )}

      {/* Collection progress */}
      {progress ? (
        <Card variant="glass" padding="md" className="relative overflow-hidden">
          <div className="pointer-events-none absolute -right-16 -top-16 h-52 w-52 rounded-full bg-sage-400/25 blur-3xl" />
          <div className="relative flex flex-col gap-5 sm:flex-row sm:items-stretch sm:justify-between sm:gap-8">
            <div className="flex-1">
              <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-ink-500">
                Monthly collection · {progress.period_month}/{progress.period_year}
              </p>
              <p className="mt-1 font-display text-3xl font-semibold text-ink-900 sm:text-4xl">
                KES {Number(progress.collected).toLocaleString()}
                <span className="ml-2 text-lg text-ink-400">
                  of {Number(progress.expected).toLocaleString()}
                </span>
              </p>
            </div>
            <div className="hidden w-px bg-ink-200/70 sm:block" aria-hidden />
            <div className="flex flex-col items-start justify-center sm:items-end">
              <p className="font-display text-5xl font-semibold leading-none text-ochre-600">
                {progress.percentage}
                <span className="text-2xl text-ink-400">%</span>
              </p>
              <Badge
                tone={Number(progress.percentage) >= 80 ? "sage" : "coral"}
                withDot
                className="mt-3"
              >
                {Number(progress.percentage) >= 80 ? "On target" : "Catch up"}
              </Badge>
            </div>
          </div>
          <div className="relative mt-5">
            <ProgressBar percentage={Number(progress.percentage)} showLabel={false} tone="sage" />
          </div>
        </Card>
      ) : (
        <Skeleton className="h-32" />
      )}

      {/* Record payment form */}
      {showForm && (
        <Card variant="glass" padding="md" className="animate-fade-up">
          <div className="mb-5">
            <p className="font-display text-lg font-semibold text-ink-900">Record manual payment</p>
            <p className="text-xs text-ink-500">
              Manually log a cash, M-Pesa, bank, or cheque payment.
            </p>
          </div>

          {!tenantsLoading && !hasTenants ? (
            <div className="rounded-md border border-dashed border-ink-300 bg-surface-raised/40 p-6 text-center">
              <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-coral-50 text-coral-600">
                <UserPlus className="h-4 w-4" />
              </div>
              <p className="font-medium text-ink-900">No active tenants yet</p>
              <p className="mx-auto mt-1 max-w-sm text-xs text-ink-500">
                Add a tenant before recording a payment. Payments must be attributed to an
                active tenant and unit.
              </p>
              <Link
                to="/tenants"
                className="mt-4 inline-flex items-center gap-1.5 rounded-full bg-ink-900 px-4 py-2 text-xs font-medium text-canvas transition-opacity hover:opacity-90"
              >
                <UserPlus className="h-3.5 w-3.5" />
                Go to tenants
              </Link>
            </div>
          ) : (
          <form onSubmit={handleSubmit(onSubmit)} className="space-y-5">
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Field label="Tenant *" error={errors.tenant?.message}>
                <select {...register("tenant")} className={inputCls} disabled={tenantsLoading}>
                  <option value={0}>
                    {tenantsLoading ? "Loading tenants…" : "Select tenant…"}
                  </option>
                  {tenants?.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.full_name} ({t.unit_label})
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Amount (KES) *" error={errors.amount?.message}>
                <input {...register("amount")} className={inputCls} />
              </Field>
              <Field label="Payment date">
                <input type="date" {...register("payment_date")} className={inputCls} />
              </Field>
              <Field label="Source">
                <select {...register("source")} className={inputCls}>
                  <option value="cash">Cash</option>
                  <option value="mpesa">M-Pesa</option>
                  <option value="bank">Bank transfer</option>
                  <option value="cheque">Cheque</option>
                </select>
              </Field>
              <Field label="Period month">
                <input type="number" min={1} max={12} {...register("period_month")} className={inputCls} />
              </Field>
              <Field label="Period year">
                <input type="number" min={2020} {...register("period_year")} className={inputCls} />
              </Field>
              <Field label="Reference">
                <input
                  {...register("reference")}
                  placeholder="M-Pesa code, receipt #"
                  className={inputCls}
                />
              </Field>
            </div>
            <div className="flex justify-end">
              <Button type="submit" loading={createPayment.isPending}>
                <CreditCard className="h-4 w-4" />
                Record payment
              </Button>
            </div>
          </form>
          )}
        </Card>
      )}

      {/* Filter chips */}
      <div className="flex flex-wrap gap-1.5">
        {SOURCES.map((s) => {
          const active = sourceFilter === s.value;
          return (
            <button
              key={s.value || "all"}
              onClick={() => setSourceFilter(s.value)}
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

      {/* Payments table */}
      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-14" />
          ))}
        </div>
      ) : !payments?.length ? (
        <Card variant="glass" padding="none" className="py-4">
          <EmptyState
            icon={<CreditCard className="h-5 w-5" />}
            title="No payments yet"
            description="Recorded payments will appear here."
          />
        </Card>
      ) : (
        <>
          <div className="hidden md:block">
            <Table>
              <THead>
                <TR>
                  <TH>Tenant</TH>
                  <TH>Unit</TH>
                  <TH className="text-right">Amount</TH>
                  <TH>Date</TH>
                  <TH>Period</TH>
                  <TH>Source</TH>
                  <TH>Reference</TH>
                </TR>
              </THead>
              <TBody>
                {payments.map((p) => (
                  <TR key={p.id}>
                    <TD>
                      <div className="flex items-center gap-3">
                        <img
                          src={avatarFor(p.tenant_name)}
                          alt=""
                          aria-hidden
                          className="h-8 w-8 rounded-full"
                        />
                        <span className="font-medium text-ink-900">{p.tenant_name}</span>
                      </div>
                    </TD>
                    <TD className="text-ink-500">
                      {p.building_name} · {p.unit_label}
                    </TD>
                    <TD className="text-right font-semibold tabular-nums text-sage-700 dark:text-sage-400">
                      KES {Number(p.amount).toLocaleString()}
                    </TD>
                    <TD className="text-ink-500">{p.payment_date}</TD>
                    <TD className="tabular-nums text-ink-500">
                      {p.period_month}/{p.period_year}
                    </TD>
                    <TD>
                      <SourceChip source={p.source} label={p.source_display} />
                    </TD>
                    <TD className="font-mono text-[11px] text-ink-400">{p.reference || "—"}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </div>

          <div className="grid gap-3 md:hidden">
            {payments.map((p) => (
              <Card key={p.id} variant="glass" padding="sm">
                <div className="flex items-start gap-3">
                  <img src={avatarFor(p.tenant_name)} alt="" aria-hidden className="h-10 w-10 rounded-full" />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate font-medium text-ink-900">{p.tenant_name}</p>
                        <p className="truncate text-[11px] text-ink-500">
                          {p.building_name} · {p.unit_label}
                        </p>
                      </div>
                      <p className="text-sm font-semibold text-sage-700 tabular-nums dark:text-sage-400">
                        KES {Number(p.amount).toLocaleString()}
                      </p>
                    </div>
                    <div className="mt-2 flex items-center justify-between">
                      <SourceChip source={p.source} label={p.source_display} />
                      <p className="text-[11px] text-ink-400">{p.payment_date}</p>
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
