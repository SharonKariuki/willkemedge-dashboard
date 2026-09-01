import { zodResolver } from "@hookform/resolvers/zod";
import { Banknote, Building2, CreditCard, Eye, EyeOff, FileText, Mail, Plus, Smartphone, Undo2, UserPlus, Wallet, X } from "lucide-react";

import { cloneElement, isValidElement, useId, useState } from "react";
import { useForm } from "react-hook-form";
import toast from "react-hot-toast";
import { Link } from "react-router-dom";
import { z } from "zod";

import ProgressBar from "@/components/ProgressBar";
import {
  Badge,
  Button,
  Card,
  DatePicker,
  EmptyState,
  ErrorState,
  PageHeader,
  Skeleton,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "@/components/ui";
import { VoidPaymentModal } from "@/features/payments/VoidPaymentModal";
import { useAuth } from "@/hooks/useAuth";
import {
  type Payment,
  useCollectionProgress,
  useCreatePayment,
  usePayments,
  useResendReceipt,
} from "@/hooks/usePayments";
import { useTenants } from "@/hooks/useTenants";
import { getErrorMessage } from "@/lib/apiError";
import { cn } from "@/lib/cn";
import { downloadPdf } from "@/lib/downloadPdf";
import { avatarFor } from "@/lib/images";

const SOURCES = [
  { value: "", label: "All" },
  { value: "cash", label: "Cash" },
  { value: "mpesa", label: "M-Pesa" },
  { value: "bank", label: "Bank" },
];

const PAYMENT_TYPES = [
  { value: "rent",     label: "Rental Income (4000)" },
  { value: "late_fee", label: "Late Fee (4010)" },
  { value: "deposit",  label: "Security Deposit (2100)" },
  { value: "other",    label: "Other Income" },
] as const;

const now = new Date();

const schema = z.object({
  tenant: z.coerce.number().min(1, "Select a tenant"),
  amount: z.string()
    .min(1, "Required")
    .refine((v) => Number(v) > 0, "Amount must be greater than 0"),
  payment_date: z.string().min(1, "Required"),
  period_month: z.coerce.number().min(1).max(12),
  period_year: z.coerce.number().min(2020).max(2100),
  source: z.string().min(1),
  payment_type: z.enum(["rent", "late_fee", "deposit", "other"]),
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
  const id = useId();
  const control = isValidElement(children)
    ? cloneElement(children as React.ReactElement<{ id?: string }>, {
        id: (children as React.ReactElement<{ id?: string }>).props.id ?? id,
      })
    : children;
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">
        {label}
      </label>
      {control}
      {error && <p className="mt-1 text-[11px] text-status-unpaid">{error}</p>}
    </div>
  );
}

export default function PaymentsPage() {
  const [sourceFilter, setSourceFilter] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [showVoided, setShowVoided] = useState(false);
  const [voidTarget, setVoidTarget] = useState<Payment | null>(null);

  // Voiding is owner-only on the API (CanForgiveMoney). Hiding the control for
  // everyone else keeps the UI honest about what it will let you finish.
  const { user } = useAuth();
  const canVoid = Boolean(user?.can_forgive_money);

  const handleDownloadReceipt = async (txnId: number) => {
    try {
      await downloadPdf(`/transactions/${txnId}/receipt-pdf/`, `wilkem-receipt-${txnId}.pdf`);
    } catch {
      toast.error("Failed to download receipt");
    }
  };

  const resendReceipt = useResendReceipt();
  const handleResendReceipt = async (paymentId: number) => {
    try {
      await resendReceipt.mutateAsync(paymentId);
      toast.success("Receipt resent");
    } catch (e) {
      toast.error(getErrorMessage(e, "Failed to resend receipt"));
    }
  };

  const filters: Record<string, string> = {};

  if (sourceFilter) filters.source = sourceFilter;
  // Voided rows are hidden by default so the list agrees with arrears and the
  // ledger; the toggle brings them back for audit.
  if (showVoided) filters.include_void = "true";

  const { data: payments, isLoading, isError, refetch } = usePayments(filters);
  const { data: progress } = useCollectionProgress();
  const { data: tenants, isLoading: tenantsLoading } = useTenants({ status: "active" });
  const createPayment = useCreatePayment();

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
      payment_type: "rent",
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
    } catch (e) {
      toast.error(getErrorMessage(e, "Failed to record payment"));
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
              variant="gold"
              onClick={() => setShowForm((v) => !v)}
            >
              {showForm ? <X className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
              {showForm ? "Cancel" : "Record Payment"}
            </Button>
          </div>
        }
      />

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
              Manually log a cash, M-Pesa, or bank payment.
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
              <DatePicker
                label="Payment date"
                {...register("payment_date")}
                error={errors.payment_date?.message}
              />

              <Field label="Source">
                <select {...register("source")} className={inputCls}>
                  <option value="cash">Cash</option>
                  <option value="mpesa">M-Pesa</option>
                  <option value="bank">Bank transfer</option>
                </select>
              </Field>
              <Field label="Type">
                <select {...register("payment_type")} className={inputCls}>
                  {PAYMENT_TYPES.map((t) => (
                    <option key={t.value} value={t.value}>{t.label}</option>
                  ))}
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
      <div className="flex flex-wrap items-center gap-1.5">
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter by payment source">
          {SOURCES.map((s) => {
            const active = sourceFilter === s.value;
            return (
              <button
                key={s.value || "all"}
                onClick={() => setSourceFilter(s.value)}
                aria-pressed={active}
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
        <button
          onClick={() => setShowVoided((v) => !v)}
          aria-pressed={showVoided}
          className={cn(
            "ml-auto inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-all",
            showVoided
              ? "bg-ink-900 text-canvas shadow-float dark:bg-ink-100 dark:text-canvas"
              : "glass text-ink-700"
          )}
          title="Show payments that have been voided"
        >
          {showVoided ? <Eye className="h-3 w-3" /> : <EyeOff className="h-3 w-3" />}
          Voided
        </button>
      </div>

      {/* Payments table */}
      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-14" />
          ))}
        </div>
      ) : isError ? (
        <Card variant="glass" padding="none" className="py-4">
          <ErrorState
            title="Payments could not be loaded."
            description="The payment history did not come back. This is usually temporary."
            onRetry={() => void refetch()}
          />
        </Card>
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
                        {p.is_void && (
                          <Badge tone="unpaid" title={p.void_reason}>Void</Badge>
                        )}
                      </div>
                    </TD>
                    <TD className="text-ink-500">
                      {p.building_name} · {p.unit_label}
                    </TD>
                    <TD
                      className={cn(
                        "text-right font-semibold tabular-nums",
                        p.is_void
                          ? "text-ink-400 line-through"
                          : "text-sage-700 dark:text-sage-400"
                      )}
                    >
                      KES {Number(p.amount).toLocaleString()}
                    </TD>
                    <TD className="text-ink-500">{p.payment_date}</TD>
                    <TD className="tabular-nums text-ink-500">
                      {p.period_month}/{p.period_year}
                    </TD>
                    <TD>
                      <SourceChip source={p.source} label={p.source_display} />
                    </TD>
                    <TD className="font-mono text-[11px] text-ink-400">
                      <div className="flex items-center gap-2">
                        {p.reference || "—"}
                        {p.transaction_id && (
                          <button
                            onClick={() => handleDownloadReceipt(p.transaction_id!)}

                            className="rounded p-1 hover:bg-sage-50 text-sage-600 transition-colors"
                            title="Download PDF Receipt"
                          >
                            <FileText className="h-3.5 w-3.5" />
                          </button>
                        )}
                        <button
                          onClick={() => handleResendReceipt(p.id)}
                          disabled={resendReceipt.isPending}
                          className="rounded p-1 hover:bg-sage-50 text-sage-600 transition-colors disabled:opacity-40"
                          title="Resend receipt by SMS + email"
                        >
                          <Mail className="h-3.5 w-3.5" />
                        </button>
                        {canVoid && !p.is_void && (
                          <button
                            onClick={() => setVoidTarget(p)}
                            className="rounded p-1 text-ink-400 transition-colors hover:bg-danger-soft hover:text-danger"
                            title="Void this payment"
                            aria-label={`Void payment of KES ${p.amount} from ${p.tenant_name}`}
                          >
                            <Undo2 className="h-3.5 w-3.5" />
                          </button>
                        )}
                      </div>
                    </TD>

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
                        <div className="flex items-center gap-2">
                          <p className="truncate font-medium text-ink-900">{p.tenant_name}</p>
                          {p.is_void && <Badge tone="unpaid">Void</Badge>}
                        </div>
                        <p className="truncate text-[11px] text-ink-500">
                          {p.building_name} · {p.unit_label}
                        </p>
                      </div>
                      <p
                        className={cn(
                          "text-sm font-semibold tabular-nums",
                          p.is_void
                            ? "text-ink-400 line-through"
                            : "text-sage-700 dark:text-sage-400"
                        )}
                      >
                        KES {Number(p.amount).toLocaleString()}
                      </p>
                    </div>
                    <div className="mt-2 flex items-center justify-between gap-2">
                      <SourceChip source={p.source} label={p.source_display} />
                      <p className="text-[11px] text-ink-400">{p.payment_date}</p>
                      <div className="flex items-center gap-3">
                        {p.transaction_id && (
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              handleDownloadReceipt(p.transaction_id!);
                            }}

                            className="flex items-center gap-1 text-[11px] text-sage-600 font-medium"
                          >
                            <FileText className="h-3 w-3" /> Receipt
                          </button>
                        )}
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleResendReceipt(p.id);
                          }}
                          disabled={resendReceipt.isPending}
                          className="flex items-center gap-1 text-[11px] text-sage-600 font-medium disabled:opacity-40"
                        >
                          <Mail className="h-3 w-3" /> Resend
                        </button>
                        {canVoid && !p.is_void && (
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setVoidTarget(p);
                            }}
                            className="flex items-center gap-1 text-[11px] font-medium text-danger"
                          >
                            <Undo2 className="h-3 w-3" /> Void
                          </button>
                        )}
                      </div>
                    </div>

                  </div>
                </div>
              </Card>
            ))}
          </div>
        </>
      )}

      {voidTarget && (
        <VoidPaymentModal
          payment={voidTarget}
          onClose={() => setVoidTarget(null)}
        />
      )}
    </div>
  );
}
