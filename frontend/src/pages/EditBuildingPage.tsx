/**
 * EditBuildingPage — /buildings/:id/edit
 *
 * Editing a building gets its own page rather than a dialog, the same as adding
 * a credit: the fields have room, the page has an address the owner can come
 * back to, and a stray click outside cannot throw the work away.
 */
import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowLeft, Check } from "lucide-react";
import { useEffect } from "react";
import { useForm } from "react-hook-form";
import toast from "react-hot-toast";
import { Link, useNavigate, useParams } from "react-router-dom";
import { z } from "zod";

import { Button, Card, ErrorState, PageHeader, Skeleton } from "@/components/ui";
import { Field, inputCls } from "@/features/tenants/shared";
import { useBuilding, useUpdateBuilding } from "@/hooks/useBuildings";
import { getErrorMessage } from "@/lib/apiError";

const schema = z.object({
  name: z.string().trim().min(1, "Name is required"),
  address: z.string().optional(),
  total_floors: z.coerce.number().int().min(1, "At least 1 floor"),
  notes: z.string().optional(),
});
type FormValues = z.infer<typeof schema>;

const BACK_TO = "/buildings";

export default function EditBuildingPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const { data: building, isLoading, isError, refetch } = useBuilding(id);
  const updateBuilding = useUpdateBuilding(id);

  const form = useForm<FormValues>({ resolver: zodResolver(schema) });
  const { register, handleSubmit, reset, formState: { errors, isDirty } } = form;

  useEffect(() => {
    if (building) {
      reset({
        name: building.name,
        address: building.address ?? "",
        total_floors: building.total_floors,
        notes: building.notes ?? "",
      });
    }
  }, [building, reset]);

  async function save(values: FormValues) {
    try {
      await updateBuilding.mutateAsync(values);
      toast.success(`${values.name} updated`);
      navigate(BACK_TO);
    } catch (e) {
      toast.error(getErrorMessage(e, "The building could not be updated."));
    }
  }

  if (isError) {
    return (
      <ErrorState
        title="This building could not be loaded."
        description="It may have been deleted. This is otherwise usually temporary."
        onRetry={() => void refetch()}
      />
    );
  }
  if (isLoading || !building) {
    return <div className="space-y-4">{Array.from({ length: 2 }).map((_, i) => <Skeleton key={i} className="h-40" />)}</div>;
  }

  return (
    <div className="space-y-6">
      <div>
        <Link to={BACK_TO} className="mb-2 inline-flex items-center gap-1 text-sm text-content-muted hover:text-content">
          <ArrowLeft className="h-4 w-4" /> Back to Buildings
        </Link>
        <PageHeader className="mb-0" eyebrow="Edit building" title={building.name} />
      </div>

      <Card variant="glass" padding="md" className="max-w-3xl animate-fade-up">
        <form onSubmit={handleSubmit(save)} className="space-y-4">
          <Field label="Name *" error={errors.name?.message}>
            <input {...register("name")} className={inputCls} />
          </Field>
          <div className="grid gap-4 sm:grid-cols-[1fr_10rem]">
            <Field label="Address">
              <input {...register("address")} className={inputCls} />
            </Field>
            <Field label="Total floors *" error={errors.total_floors?.message}>
              <input type="number" min={1} {...register("total_floors")} className={inputCls} />
            </Field>
          </div>
          <Field label="Notes">
            <textarea rows={4} {...register("notes")} className={inputCls} />
          </Field>
          <p className="text-xs text-content-muted">
            Unit rents are changed from the building&rsquo;s card on the Buildings page, under{" "}
            <span className="font-medium text-content">Edit unit rents &amp; repairs</span>.
          </p>
          <div className="flex justify-end gap-2 border-t border-hairline pt-4">
            <Button type="button" variant="ghost" onClick={() => navigate(BACK_TO)}>Cancel</Button>
            <Button type="submit" loading={updateBuilding.isPending} disabled={!isDirty}>
              <Check className="h-4 w-4" /> Save changes
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}
