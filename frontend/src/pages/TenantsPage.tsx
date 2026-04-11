/**
 * Tenant list page with search, status filter, and add tenant modal.
 */
import { zodResolver } from "@hookform/resolvers/zod";
import { Plus, Search, UserPlus, X } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import toast from "react-hot-toast";
import { z } from "zod";

import { useCreateTenant, useTenants } from "@/hooks/useTenants";
import { useUnits } from "@/hooks/useUnits";

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

export default function TenantsPage() {
  const [statusFilter, setStatusFilter] = useState("");
  const [search, setSearch] = useState("");
  const [showForm, setShowForm] = useState(false);

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

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <h2 className="text-2xl font-bold text-slate-900">Tenants</h2>
        <button
          onClick={() => setShowForm(!showForm)}
          className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800"
        >
          {showForm ? <X className="h-4 w-4" /> : <UserPlus className="h-4 w-4" />}
          {showForm ? "Cancel" : "Register Tenant"}
        </button>
      </div>

      {/* Add tenant form */}
      {showForm && (
        <form
          onSubmit={handleSubmit(onSubmit)}
          className="rounded-xl border border-slate-200 bg-white p-5 space-y-5"
        >
          <h3 className="text-base font-semibold text-slate-900">New Tenant</h3>

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <div>
              <label className="block text-sm font-medium text-slate-700">First Name</label>
              <input {...register("first_name")} className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
              {errors.first_name && <p className="mt-1 text-xs text-red-600">{errors.first_name.message}</p>}
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700">Last Name</label>
              <input {...register("last_name")} className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
              {errors.last_name && <p className="mt-1 text-xs text-red-600">{errors.last_name.message}</p>}
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700">ID Number</label>
              <input {...register("id_number")} className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
              {errors.id_number && <p className="mt-1 text-xs text-red-600">{errors.id_number.message}</p>}
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700">Phone</label>
              <input {...register("phone")} className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" placeholder="+254..." />
              {errors.phone && <p className="mt-1 text-xs text-red-600">{errors.phone.message}</p>}
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700">Email</label>
              <input type="email" {...register("email")} className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700">Unit</label>
              <select {...register("unit")} className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm">
                <option value={0}>Select a vacant unit...</option>
                {vacantUnits?.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.building_name} — {u.label} (KES {Number(u.monthly_rent).toLocaleString()})
                  </option>
                ))}
              </select>
              {errors.unit && <p className="mt-1 text-xs text-red-600">{errors.unit.message}</p>}
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700">Monthly Rent (KES)</label>
              <input {...register("monthly_rent")} className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
              {errors.monthly_rent && <p className="mt-1 text-xs text-red-600">{errors.monthly_rent.message}</p>}
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700">Deposit Paid (KES)</label>
              <input {...register("deposit_paid")} className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700">Move-in Date</label>
              <input type="date" {...register("move_in_date")} className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
              {errors.move_in_date && <p className="mt-1 text-xs text-red-600">{errors.move_in_date.message}</p>}
            </div>
          </div>

          <div className="flex gap-3 pt-2">
            <label className="block text-sm font-medium text-slate-700 w-full">
              Emergency Contact
              <input {...register("emergency_contact")} className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
            </label>
            <label className="block text-sm font-medium text-slate-700 w-full">
              Emergency Phone
              <input {...register("emergency_phone")} className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
            </label>
          </div>

          <button
            type="submit"
            disabled={createTenant.isPending}
            className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-60"
          >
            <Plus className="h-4 w-4" />
            {createTenant.isPending ? "Registering..." : "Register & Move In"}
          </button>
        </form>
      )}

      {/* Search + filter */}
      <div className="flex flex-wrap gap-3">
        <div className="relative flex-1 min-w-[200px] max-w-sm">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search name, ID, phone..."
            className="block w-full rounded-lg border border-slate-300 bg-white py-2 pl-9 pr-3 text-sm"
          />
        </div>
        <div className="flex gap-1">
          {TENANT_STATUSES.map((s) => (
            <button
              key={s.value}
              onClick={() => setStatusFilter(s.value)}
              className={`rounded-lg px-3 py-2 text-xs font-medium transition-colors ${
                statusFilter === s.value
                  ? "bg-slate-900 text-white"
                  : "bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50"
              }`}
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tenant table */}
      {isLoading ? (
        <div className="py-12 text-center text-slate-500">Loading tenants...</div>
      ) : !tenants?.length ? (
        <div className="py-12 text-center text-slate-500">No tenants found.</div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs font-medium uppercase text-slate-500">
              <tr>
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Unit</th>
                <th className="px-4 py-3">Phone</th>
                <th className="px-4 py-3">Rent (KES)</th>
                <th className="px-4 py-3">Move-in</th>
                <th className="px-4 py-3">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {tenants.map((t) => (
                <tr key={t.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3 font-medium text-slate-900">{t.full_name}</td>
                  <td className="px-4 py-3 text-slate-600">
                    {t.building_name} — {t.unit_label}
                  </td>
                  <td className="px-4 py-3 text-slate-600">{t.phone}</td>
                  <td className="px-4 py-3 text-slate-600">
                    {Number(t.monthly_rent).toLocaleString()}
                  </td>
                  <td className="px-4 py-3 text-slate-600">{t.move_in_date}</td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
                        t.status === "active"
                          ? "bg-green-100 text-green-800"
                          : "bg-slate-100 text-slate-600"
                      }`}
                    >
                      {t.status_display}
                    </span>
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
