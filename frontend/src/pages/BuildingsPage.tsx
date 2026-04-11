/**
 * Buildings index + add/edit building form.
 */
import { zodResolver } from "@hookform/resolvers/zod";
import { Building2, Plus, X } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import toast from "react-hot-toast";
import { z } from "zod";

import { useBuildings, useCreateBuilding } from "@/hooks/useBuildings";

const schema = z.object({
  name: z.string().min(1, "Name is required"),
  address: z.string().optional(),
  total_floors: z.coerce.number().int().min(1, "At least 1 floor"),
});

type FormValues = z.infer<typeof schema>;

export default function BuildingsPage() {
  const { data: buildings, isLoading } = useBuildings();
  const createBuilding = useCreateBuilding();
  const [showForm, setShowForm] = useState(false);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { name: "", address: "", total_floors: 1 },
  });

  const onSubmit = async (values: FormValues) => {
    try {
      await createBuilding.mutateAsync(values);
      toast.success("Building created");
      reset();
      setShowForm(false);
    } catch {
      toast.error("Failed to create building");
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-slate-900">Buildings</h2>
        <button
          onClick={() => setShowForm(!showForm)}
          className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800"
        >
          {showForm ? <X className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
          {showForm ? "Cancel" : "Add Building"}
        </button>
      </div>

      {/* Add building form */}
      {showForm && (
        <form
          onSubmit={handleSubmit(onSubmit)}
          className="rounded-xl border border-slate-200 bg-white p-5 space-y-4"
        >
          <div className="grid gap-4 sm:grid-cols-3">
            <div>
              <label className="block text-sm font-medium text-slate-700">Name</label>
              <input
                {...register("name")}
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
              {errors.name && <p className="mt-1 text-xs text-red-600">{errors.name.message}</p>}
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700">Address</label>
              <input
                {...register("address")}
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700">Total Floors</label>
              <input
                type="number"
                min={1}
                {...register("total_floors")}
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
              {errors.total_floors && (
                <p className="mt-1 text-xs text-red-600">{errors.total_floors.message}</p>
              )}
            </div>
          </div>
          <button
            type="submit"
            disabled={createBuilding.isPending}
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-60"
          >
            {createBuilding.isPending ? "Creating..." : "Create Building"}
          </button>
        </form>
      )}

      {/* Building cards */}
      {isLoading ? (
        <div className="py-12 text-center text-slate-500">Loading buildings...</div>
      ) : !buildings?.length ? (
        <div className="py-12 text-center text-slate-500">No buildings yet. Add one above.</div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {buildings.map((b) => (
            <div
              key={b.id}
              className="rounded-xl border border-slate-200 bg-white p-5 transition-shadow hover:shadow-md"
            >
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-slate-100">
                  <Building2 className="h-5 w-5 text-slate-600" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-slate-900">{b.name}</h3>
                  {b.address && (
                    <p className="text-xs text-slate-500">{b.address}</p>
                  )}
                </div>
              </div>
              <div className="mt-4 flex gap-6 text-center">
                <div>
                  <p className="text-xl font-bold text-slate-900">{b.unit_count}</p>
                  <p className="text-xs text-slate-500">Total Units</p>
                </div>
                <div>
                  <p className="text-xl font-bold text-green-600">{b.occupied_count}</p>
                  <p className="text-xs text-slate-500">Occupied</p>
                </div>
                <div>
                  <p className="text-xl font-bold text-slate-400">
                    {b.unit_count - b.occupied_count}
                  </p>
                  <p className="text-xs text-slate-500">Vacant</p>
                </div>
              </div>
              <p className="mt-3 text-xs text-slate-400">{b.total_floors} floor(s)</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
