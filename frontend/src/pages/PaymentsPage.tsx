/**
 * Payments page — record manual payments + view payment history.
 */
import { zodResolver } from "@hookform/resolvers/zod";
import { CreditCard, Plus, X } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import toast from "react-hot-toast";
import { z } from "zod";

import ProgressBar from "@/components/ProgressBar";
import { useCollectionProgress, useCreatePayment, usePayments } from "@/hooks/usePayments";
import { useTenants } from "@/hooks/useTenants";

const SOURCES = [
  { value: "", label: "All Sources" },
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

// ---------------------------------------------------------------------------
// Source badge — colour-coded by payment method
// ---------------------------------------------------------------------------
const SOURCE_STYLES: Record<string, string> = {
  mpesa:  "bg-green-100  text-green-800",
  bank:   "bg-blue-100   text-blue-800",
  cash:   "bg-amber-100  text-amber-800",
  cheque: "bg-purple-100 text-purple-800",
};

function SourceBadge({ source, label }: { source: string; label: string }) {
  const cls = SOURCE_STYLES[source] ?? "bg-slate-100 text-slate-700";
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ${cls}`}>
      {source === "mpesa"  && <span>📱</span>}
      {source === "bank"   && <span>🏦</span>}
      {source === "cash"   && <span>💵</span>}
      {source === "cheque" && <span>📝</span>}
      {label}
    </span>
  );
}

export default function PaymentsPage() {
  const [sourceFilter, setSourceFilter] = useState("");
  const [showForm, setShowForm] = useState(false);

  const filters: Record<string, string> = {};
  if (sourceFilter) filters.source = sourceFilter;

  const { data: payments, isLoading } = usePayments(filters);
  const { data: progress } = useCollectionProgress();
  const { data: tenants } = useTenants({ status: "active" });
  const createPayment = useCreatePayment();

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
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <h2 className="text-2xl font-bold text-slate-900">Payments</h2>
        <button
          onClick={() => setShowForm(!showForm)}
          className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800"
        >
          {showForm ? <X className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
          {showForm ? "Cancel" : "Record Payment"}
        </button>
      </div>

      {/* Collection progress */}
      {progress && (
        <div className="rounded-xl border border-slate-200 bg-white p-5">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-slate-700">
                Monthly Collection — {progress.period_month}/{progress.period_year}
              </p>
              <p className="mt-1 text-xs text-slate-500">
                KES {Number(progress.collected).toLocaleString()} of{" "}
                KES {Number(progress.expected).toLocaleString()}
              </p>
            </div>
            <p className="text-2xl font-bold text-slate-900">{progress.percentage}%</p>
          </div>
          <div className="mt-3">
            <ProgressBar percentage={Number(progress.percentage)} showLabel={false} />
          </div>
        </div>
      )}

      {/* Record payment form */}
      {showForm && (
        <form
          onSubmit={handleSubmit(onSubmit)}
          className="rounded-xl border border-slate-200 bg-white p-5 space-y-4"
        >
          <h3 className="text-base font-semibold text-slate-900">Record Manual Payment</h3>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <label className="block text-sm font-medium text-slate-700">Tenant</label>
              <select {...register("tenant")} className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm">
                <option value={0}>Select tenant...</option>
                {tenants?.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.full_name} ({t.unit_label})
                  </option>
                ))}
              </select>
              {errors.tenant && <p className="mt-1 text-xs text-red-600">{errors.tenant.message}</p>}
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700">Amount (KES)</label>
              <input {...register("amount")} className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
              {errors.amount && <p className="mt-1 text-xs text-red-600">{errors.amount.message}</p>}
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700">Payment Date</label>
              <input type="date" {...register("payment_date")} className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700">Source</label>
              <select {...register("source")} className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm">
                <option value="cash">Cash</option>
                <option value="mpesa">M-Pesa</option>
                <option value="bank">Bank Transfer</option>
                <option value="cheque">Cheque</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700">Period Month</label>
              <input type="number" min={1} max={12} {...register("period_month")} className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700">Period Year</label>
              <input type="number" min={2020} {...register("period_year")} className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700">Reference</label>
              <input {...register("reference")} placeholder="M-Pesa code, receipt #..." className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
            </div>
          </div>
          <button
            type="submit"
            disabled={createPayment.isPending}
            className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-60"
          >
            <CreditCard className="h-4 w-4" />
            {createPayment.isPending ? "Recording..." : "Record Payment"}
          </button>
        </form>
      )}

      {/* Filter */}
      <div className="flex gap-1">
        {SOURCES.map((s) => (
          <button
            key={s.value}
            onClick={() => setSourceFilter(s.value)}
            className={`rounded-lg px-3 py-2 text-xs font-medium transition-colors ${
              sourceFilter === s.value
                ? "bg-slate-900 text-white"
                : "bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50"
            }`}
          >
            {s.label}
          </button>
        ))}
      </div>

      {/* Payments table */}
      {isLoading ? (
        <div className="py-12 text-center text-slate-500">Loading payments...</div>
      ) : !payments?.length ? (
        <div className="py-12 text-center text-slate-500">No payments found.</div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs font-medium uppercase text-slate-500">
              <tr>
                <th className="px-4 py-3">Tenant</th>
                <th className="px-4 py-3">Unit</th>
                <th className="px-4 py-3">Amount</th>
                <th className="px-4 py-3">Date</th>
                <th className="px-4 py-3">Period</th>
                <th className="px-4 py-3">Source</th>
                <th className="px-4 py-3">Reference</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {payments.map((p) => (
                <tr key={p.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3 font-medium text-slate-900">{p.tenant_name}</td>
                  <td className="px-4 py-3 text-slate-600">
                    {p.building_name} — {p.unit_label}
                  </td>
                  <td className="px-4 py-3 font-semibold text-green-700">
                    KES {Number(p.amount).toLocaleString()}
                  </td>
                  <td className="px-4 py-3 text-slate-600">{p.payment_date}</td>
                  <td className="px-4 py-3 text-slate-600">
                    {p.period_month}/{p.period_year}
                  </td>
                  <td className="px-4 py-3">
                    <SourceBadge source={p.source} label={p.source_display} />
                  </td>
                  <td className="px-4 py-3 text-slate-400 font-mono text-xs">
                    {p.reference || "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
