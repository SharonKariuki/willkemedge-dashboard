/**
 * ManualIncomePage — record non-tenant income (e.g. farm produce sales).
 *
 * Rent flows through Payments; this is for income that has no tenant. Buildings
 * flagged expenses-only (Baobab Karen) are excluded from the building picker and
 * the server rejects income for them, so the "expenses only" rule holds either
 * way.
 */
import { zodResolver } from "@hookform/resolvers/zod";
import { PlusCircle, Sprout, Trash2 } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import toast from "react-hot-toast";
import { z } from "zod";

import {
  Button, Card, DatePicker, EmptyState, ErrorState,
  PageHeader, Skeleton, Table, TBody, TD, TH, THead, TR,
} from "@/components/ui";
import { useBuildings } from "@/hooks/useBuildings";
import {
  useCreateManualIncome, useDeleteManualIncome, useIncomeAccounts, useManualIncome,
} from "@/hooks/useManualIncome";
import { getErrorMessage } from "@/lib/apiError";

const inputCls =
  "w-full rounded-md bg-surface-raised hairline px-3 py-2.5 text-sm text-ink-900 placeholder:text-ink-400 focus:outline-none focus:ring-2 focus:ring-sage-500/40";

const schema = z.object({
  date: z.string().min(1, "Date is required"),
  building: z.coerce.number().min(1, "Property is required"),
  account: z.coerce.number().min(1, "Income account is required"),
  amount: z.string().min(1, "Amount is required").refine((v) => Number(v) > 0, "Must be greater than 0"),
  description: z.string().min(2, "Description is required"),
  reference: z.string().optional(),
  period_month: z.coerce.number().min(1).max(12),
  period_year: z.coerce.number().min(2000).max(2100),
});
type FormData = z.infer<typeof schema>;

export default function ManualIncomePage() {
  const now = new Date();
  const [showForm, setShowForm] = useState(false);
  const { data: income, isLoading, isError, refetch } = useManualIncome();
  const { data: buildings } = useBuildings();
  const { data: accounts } = useIncomeAccounts();
  const create = useCreateManualIncome();
  const remove = useDeleteManualIncome();

  // Only income-allowing properties (farms, rentals) — never Baobab Karen.
  const incomeProperties = (buildings ?? []).filter((b) => b.allows_income !== false);

  const form = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: {
      date: now.toISOString().split("T")[0],
      period_month: now.getMonth() + 1,
      period_year: now.getFullYear(),
    },
  });

  const onSubmit = (values: FormData) => {
    create.mutate(
      { ...values, reference: values.reference ?? "" },
      {
        onSuccess: () => {
          toast.success("Income recorded");
          form.reset({
            date: now.toISOString().split("T")[0],
            period_month: now.getMonth() + 1,
            period_year: now.getFullYear(),
          });
          setShowForm(false);
        },
        onError: (e) => toast.error(getErrorMessage(e, "Failed to record income")),
      },
    );
  };

  const total = income?.reduce((s, i) => s + parseFloat(i.amount), 0) ?? 0;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Income"
        title="Manual Income"
        description="Record non-tenant income such as farm produce sales. Rent is recorded under Payments."
        actions={
          <Button onClick={() => setShowForm((v) => !v)}>
            <PlusCircle className="h-4 w-4" />
            {showForm ? "Cancel" : "Record Income"}
          </Button>
        }
      />

      {showForm && (
        <Card variant="glass" padding="md" className="animate-fade-up">
          <p className="mb-4 font-display text-lg font-semibold text-ink-900">New income entry</p>
          <form onSubmit={form.handleSubmit(onSubmit)} className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <DatePicker label="Date *" {...form.register("date")} error={form.formState.errors.date?.message} />

            <label className="block">
              <span className="mb-1 block text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">Property *</span>
              <select {...form.register("building")} className={inputCls}>
                <option value="">Select property…</option>
                {incomeProperties.map((b) => (
                  <option key={b.id} value={b.id}>{b.name}</option>
                ))}
              </select>
              {form.formState.errors.building && (
                <p className="mt-1 text-[11px] text-status-unpaid">{form.formState.errors.building.message}</p>
              )}
            </label>
            <label className="block">
              <span className="mb-1 block text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">Income account *</span>
              <select {...form.register("account")} className={inputCls}>
                <option value="">Select GL account…</option>
                {accounts?.map((a) => (
                  <option key={a.id} value={a.id}>{a.code} · {a.name}</option>
                ))}
              </select>
              {form.formState.errors.account && (
                <p className="mt-1 text-[11px] text-status-unpaid">{form.formState.errors.account.message}</p>
              )}
            </label>
            <label className="block">
              <span className="mb-1 block text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">Amount (KES) *</span>
              <input {...form.register("amount")} className={inputCls} placeholder="0.00" />
              {form.formState.errors.amount && (
                <p className="mt-1 text-[11px] text-status-unpaid">{form.formState.errors.amount.message}</p>
              )}
            </label>
            <label className="block sm:col-span-2">
              <span className="mb-1 block text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">Description *</span>
              <input {...form.register("description")} className={inputCls} placeholder="e.g. Maize sale" />
              {form.formState.errors.description && (
                <p className="mt-1 text-[11px] text-status-unpaid">{form.formState.errors.description.message}</p>
              )}
            </label>
            <div className="lg:col-span-3">
              <Button type="submit" loading={create.isPending} variant="primary">Save income</Button>
            </div>
          </form>
        </Card>
      )}

      <Card variant="glass" padding="md">
        <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-ink-500">Total recorded</p>
        <p className="mt-1 font-display text-4xl font-semibold text-sage-600">KES {total.toLocaleString()}</p>
      </Card>

      {isLoading ? (
        <div className="space-y-2">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-14" />)}</div>
      ) : isError ? (
        <ErrorState title="Income could not be loaded." description="This is usually temporary." onRetry={() => void refetch()} />
      ) : !income?.length ? (
        <EmptyState icon={<Sprout className="h-5 w-5" />} title="No income recorded yet" description="Record farm produce sales and other non-tenant income here." />
      ) : (
        <Table>
          <THead>
            <TR><TH>Date</TH><TH>Property</TH><TH>Account</TH><TH>Description</TH><TH className="text-right">Amount</TH><TH /></TR>
          </THead>
          <TBody>
            {income.map((i) => (
              <TR key={i.id}>
                <TD className="text-ink-500">{i.date}</TD>
                <TD>{i.building_name}</TD>
                <TD className="text-ink-500">{i.account_code} · {i.account_name}</TD>
                <TD>{i.description}</TD>
                <TD className="text-right font-medium tabular-nums text-sage-600">{Number(i.amount).toLocaleString()}</TD>
                <TD className="text-right">
                  <button
                    onClick={() => remove.mutate(i.id)}
                    className="text-ink-400 hover:text-status-unpaid"
                    aria-label={`Delete income ${i.description}`}
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      )}
    </div>
  );
}
