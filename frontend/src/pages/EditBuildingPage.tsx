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
import { PhotoPicker } from "@/features/buildings/PhotoPicker";
import { Field, inputCls } from "@/features/tenants/shared";
import {
  useBuilding,
  useBuildingPhotoSrc,
  useRemoveBuildingPhoto,
  useSetBuildingPhoto,
  useUpdateBuilding,
} from "@/hooks/useBuildings";
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
  const setPhoto = useSetBuildingPhoto();
  const removePhoto = useRemoveBuildingPhoto();
  const photoSrc = useBuildingPhotoSrc(building);

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

  // A photo change is saved straight away, apart from the form: it is its own
  // upload, and a half-typed form should not hold it back.
  async function changePhoto(blob: Blob) {
    try {
      await setPhoto.mutateAsync({ id, photo: blob });
      toast.success("Photo updated");
    } catch (e) {
      toast.error(getErrorMessage(e, "The photo could not be uploaded."));
    }
  }

  async function dropPhoto() {
    try {
      await removePhoto.mutateAsync(id);
      toast.success("Photo removed. A stock picture is shown instead.");
    } catch (e) {
      toast.error(getErrorMessage(e, "The photo could not be removed."));
    }
  }

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

      <Card variant="glass" padding="md" className="animate-fade-up">
        <form onSubmit={handleSubmit(save)} className="space-y-6">
          <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(16rem,22rem)]">
          <div className="min-w-0 space-y-4">
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
            <textarea rows={5} {...register("notes")} className={inputCls} />
          </Field>
          <p className="text-xs text-content-muted">
            Unit rents are changed from the building&rsquo;s card on the Buildings page, under{" "}
            <span className="font-medium text-content">Edit unit rents &amp; repairs</span>.
          </p>
          </div>
          <PhotoPicker
            src={photoSrc}
            isPlaceholder={!building.has_photo}
            onPick={(blob) => void changePhoto(blob)}
            onRemove={() => void dropPhoto()}
            busy={setPhoto.isPending || removePhoto.isPending}
          />
          </div>
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
