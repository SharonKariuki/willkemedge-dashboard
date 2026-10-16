/**
 * MoveInAgainForm — a moved-out tenant takes a vacant unit again.
 *
 * Any vacant unit in the portfolio: the one they left, another in the same
 * block, or one in another property. The API registers it as a NEW tenancy with
 * the person's details and KYC carried over, and leaves the old one exactly as
 * it was moved out, so this page's history stays true. On success we go to the
 * new tenancy's page.
 */
import { zodResolver } from "@hookform/resolvers/zod";
import { LogIn } from "lucide-react";
import { useForm } from "react-hook-form";
import toast from "react-hot-toast";
import { useNavigate } from "react-router-dom";
import { z } from "zod";

import { Button, DatePicker } from "@/components/ui";
import { Field, inputCls } from "@/features/tenants/shared";
import { useMoveInAgain } from "@/hooks/useTenants";
import { useUnits } from "@/hooks/useUnits";
import { getErrorMessage } from "@/lib/apiError";
import { todayIso } from "@/lib/dates";
import { isNonNegativeAmountOrBlank, isPositiveAmount } from "@/lib/formValidators";
import type { TenantDetail } from "@/lib/types";

const schema = z
  .object({
    unit: z.coerce.number().min(1, "Select a unit"),
    monthly_rent: z.string().min(1, "Required").refine(isPositiveAmount, "Enter an amount greater than 0"),
    move_in_date: z.string().min(1, "Required"),
    deposit_paid: z.string().optional().refine(isNonNegativeAmountOrBlank, "Enter a valid amount"),
    deposit_source: z.enum(["cash", "mpesa", "bank", "cheque"]).optional(),
    deposit_reference: z.string().optional(),
  });
type FormValues = z.infer<typeof schema>;

export function MoveInAgainForm({ tenant, onCancel }: { tenant: TenantDetail; onCancel: () => void }) {
  const navigate = useNavigate();
  const { data: vacantUnits } = useUnits({ status: "vacant" });
  const moveIn = useMoveInAgain(tenant.id);
  const {
    register, handleSubmit, watch, setValue, formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { deposit_paid: "0", deposit_source: "cash", move_in_date: todayIso() },
  });
  const booksMoney = Number(watch("deposit_paid") ?? 0) > 0;
  const unitField = register("unit");

  const onSubmit = async (values: FormValues) => {
    try {
      const created = await moveIn.mutateAsync({ ...values, deposit_paid: values.deposit_paid || "0" });
      toast.success(`${tenant.full_name} moved into ${created.building_name} · ${created.unit_label}`);
      navigate(`/tenants/${created.id}`);
    } catch (e) {
      toast.error(getErrorMessage(e, "Failed to move the tenant in"));
    }
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
      <div>
        <p className="font-semibold text-content">Move {tenant.full_name} in again</p>
        <p className="mt-1 text-xs text-content-muted">
          Starts a new tenancy with their details and KYC carried over. This tenancy
          ({tenant.building_name} · {tenant.unit_label}) stays on record as moved out.
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Unit *" error={errors.unit?.message}>
          <select
            {...unitField}
            onChange={(e) => {
              void unitField.onChange(e);
              // Start from the unit's listed rent; the office can still change it.
              const unit = vacantUnits?.find((u) => u.id === Number(e.target.value));
              if (unit) setValue("monthly_rent", String(Number(unit.monthly_rent)));
            }}
            className={inputCls}
          >
            <option value={0}>Select a vacant unit…</option>
            {vacantUnits?.map((u) => (
              <option key={u.id} value={u.id}>
                {u.building_name} — {u.label}{u.id === tenant.unit ? " (their previous unit)" : ""}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Monthly rent (KES) *" error={errors.monthly_rent?.message}>
          <input {...register("monthly_rent")} className={inputCls} />
        </Field>
        <DatePicker label="Move-in date *" {...register("move_in_date")} error={errors.move_in_date?.message} />
        <Field label="Deposit paid (KES)" error={errors.deposit_paid?.message}>
          <input {...register("deposit_paid")} className={inputCls} />
        </Field>
        <Field label="Deposit received via">
          <select {...register("deposit_source")} className={inputCls} disabled={!booksMoney}>
            <option value="cash">Cash</option>
            <option value="mpesa">M-Pesa</option>
            <option value="bank">Bank Transfer</option>
            <option value="cheque">Cheque</option>
          </select>
        </Field>
        <Field label="Reference">
          <input
            {...register("deposit_reference")}
            className={inputCls}
            disabled={!booksMoney}
            placeholder="M-Pesa code / receipt no."
          />
        </Field>
      </div>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onCancel}>Cancel</Button>
        <Button type="submit" loading={moveIn.isPending}><LogIn className="h-4 w-4" /> Confirm move-in</Button>
      </div>
    </form>
  );
}
