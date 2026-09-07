/**
 * WaterReadingsPage — /water
 *
 * Staff enter a current water meter reading per unit. The system pre-fills the
 * previous reading, computes consumption (current − previous) at the building's
 * tariff, and bills it as a water charge (posts to the GL, shows as "Other
 * Charges" on the statement). Backend: /api/utility-charges/reading/.
 */
import { zodResolver } from "@hookform/resolvers/zod";
import { AlertTriangle, Droplets, Gauge } from "lucide-react";
import { useEffect, useMemo } from "react";
import { useForm } from "react-hook-form";
import toast from "react-hot-toast";
import { z } from "zod";

import {
  Badge, Button, Card, EmptyState, PageHeader, Skeleton,
  Table, TBody, TD, TH, THead, TR,
} from "@/components/ui";
import { useTenants } from "@/hooks/useTenants";
import { useCaptureReading, usePreviousReading, useUtilityCharges } from "@/hooks/useWaterReadings";
import { getErrorMessage } from "@/lib/apiError";

const inputCls =
  "w-full rounded-md bg-surface-raised hairline px-3 py-2.5 text-sm text-ink-900 placeholder:text-ink-400 focus:outline-none focus:ring-2 focus:ring-sage-500/40";

const now = new Date();
const schema = z.object({
  tenant: z.coerce.number().min(1, "Select a unit"),
  period_month: z.coerce.number().min(1).max(12),
  period_year: z.coerce.number().min(2020).max(2100),
  closing_reading: z.string().min(1, "Current reading is required"),
  opening_reading: z.string().optional(),
  // The meter is the record; an opening that disagrees with the closing figure
  // already on file is a typo unless staff say the hardware was swapped. The
  // backend rejects the mismatch, so the form makes the claim explicit rather
  // than letting them discover it as a 400.
  meter_replaced: z.boolean().optional(),
});
type FormData = z.infer<typeof schema>;

export default function WaterReadingsPage() {
  const { data: tenants } = useTenants({ status: "active" });
  const capture = useCaptureReading();

  const form = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: {
      period_month: now.getMonth() + 1,
      period_year: now.getFullYear(),
      meter_replaced: false,
    },
  });

  const tenantId = Number(form.watch("tenant")) || null;
  const closing = form.watch("closing_reading");
  const month = Number(form.watch("period_month")) || undefined;
  const year = Number(form.watch("period_year")) || undefined;
  const replaced = form.watch("meter_replaced") ?? false;
  // Asked per period, so backfilling August carries July's closing figure
  // rather than whatever month happens to be newest on file.
  const { data: prev } = usePreviousReading(tenantId, month, year);
  const { data: charges, isLoading } = useUtilityCharges(tenantId);

  // Pre-fill the opening reading from the reading the meter closed on before
  // this period. A replaced meter starts its own chain, so leave it blank.
  useEffect(() => {
    if (replaced) {
      form.setValue("opening_reading", "");
    } else if (prev?.previous_reading != null) {
      form.setValue("opening_reading", String(prev.previous_reading));
    } else {
      form.setValue("opening_reading", "");
    }
  }, [prev, replaced, form]);

  // Watch the opening field so the preview updates when a unit with no prior
  // reading has its opening typed in manually (not just on closing/prev change).
  const opening = form.watch("opening_reading");
  const readings = useMemo(() => {
    // "" is falsy, "0" is not — a meter genuinely starting at zero still previews.
    if (!closing || !opening) return null;
    const open = Number(opening);
    const close = Number(closing);
    if (Number.isNaN(open) || Number.isNaN(close)) return null;
    return { open, close };
  }, [closing, opening]);

  // A closing below the opening is the one mistake that must never be billed
  // quietly. The old preview just went blank, which reads as "nothing to show
  // yet" — so staff submitted anyway and met a 400 with no idea which figure
  // was wrong.
  const backwards = !!readings && readings.close < readings.open;

  const preview = useMemo(() => {
    if (!readings || backwards) return null;
    const rate = Number(prev?.water_rate_per_unit ?? 0);
    const units = readings.close - readings.open;
    return { units, amount: units * rate, rate };
  }, [readings, backwards, prev]);

  const onSubmit = (values: FormData) => {
    capture.mutate(
      {
        tenant: values.tenant,
        period_month: values.period_month,
        period_year: values.period_year,
        closing_reading: values.closing_reading,
        opening_reading: values.opening_reading || undefined,
        meter_replaced: values.meter_replaced || false,
      },
      {
        onSuccess: () => {
          toast.success("Water charge recorded");
          form.setValue("closing_reading", "");
          form.setValue("meter_replaced", false);
        },
        onError: (e) => toast.error(getErrorMessage(e, "Could not record the reading")),
      },
    );
  };

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Utilities"
        title="Water Readings"
        description="Enter each unit's current meter reading. Consumption is billed at the building's tariff and appears as Other Charges on the statement."
      />

      <Card variant="glass" padding="md">
        <form onSubmit={form.handleSubmit(onSubmit)} className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <label className="block sm:col-span-2">
            <span className="mb-1 block text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">Unit / Tenant *</span>
            <select {...form.register("tenant")} className={inputCls}>
              <option value="">Select a unit…</option>
              {tenants?.map((t) => (
                <option key={t.id} value={t.id}>{t.unit_label} · {t.full_name}</option>
              ))}
            </select>
            {form.formState.errors.tenant && (
              <p className="mt-1 text-[11px] text-status-unpaid">{form.formState.errors.tenant.message}</p>
            )}
          </label>
          <div className="block">
            <label className="block">
              <span className="mb-1 block text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">Previous reading</span>
              <input
                {...form.register("opening_reading")}
                className={inputCls}
                placeholder="—"
                inputMode="decimal"
                readOnly={prev?.previous_reading != null && !replaced}
              />
              <span className="mt-1 block text-[11px] text-ink-400">
                {replaced
                  ? "New meter — enter the dial it starts on"
                  : prev?.previous_reading != null
                    ? "Carried from the last reading before this month"
                    : "No prior reading — enter the opening"}
              </span>
            </label>
            <label className="mt-2 flex items-center gap-2 text-[11px] text-ink-500">
              <input type="checkbox" {...form.register("meter_replaced")} className="h-3.5 w-3.5 accent-sage-600" />
              Meter was replaced — the dial restarted
            </label>
          </div>
          <label className="block">
            <span className="mb-1 block text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">Current reading *</span>
            <input {...form.register("closing_reading")} className={inputCls} placeholder="e.g. 1209" inputMode="decimal" />
            {form.formState.errors.closing_reading && (
              <p className="mt-1 text-[11px] text-status-unpaid">{form.formState.errors.closing_reading.message}</p>
            )}
          </label>
          <label className="block">
            <span className="mb-1 block text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">Month *</span>
            <select {...form.register("period_month")} className={inputCls}>
              {Array.from({ length: 12 }, (_, i) => (
                <option key={i + 1} value={i + 1}>
                  {new Date(2026, i).toLocaleString("default", { month: "long" })}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">Year *</span>
            <input type="number" {...form.register("period_year")} className={inputCls} />
          </label>
          <div className="flex items-end sm:col-span-2 lg:col-span-2">
            {backwards && readings ? (
              <div className="flex items-start gap-2 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                Current reading {readings.close} is below the previous reading {readings.open} — a meter cannot run backwards.
              </div>
            ) : preview ? (
              <div className="flex items-center gap-2 rounded-md bg-info-soft px-3 py-2 text-sm text-teal-700">
                <Gauge className="h-4 w-4" />
                {preview.units} units × KES {preview.rate} = <strong>KES {preview.amount.toLocaleString()}</strong>
              </div>
            ) : (
              <p className="text-sm text-ink-400">Enter a current reading to preview the charge.</p>
            )}
          </div>
          <div className="lg:col-span-4">
            <Button type="submit" loading={capture.isPending} variant="primary">
              <Droplets className="h-4 w-4" /> Record reading
            </Button>
          </div>
        </form>
      </Card>

      {tenantId && (
        <Card padding="none">
          <div className="border-b border-hairline px-5 py-4">
            <h2 className="font-semibold text-content">Recent water charges</h2>
          </div>
          {isLoading ? (
            <div className="space-y-2 p-4">{Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-10" />)}</div>
          ) : charges?.length ? (
            <Table>
              <THead>
                <TR><TH>Period</TH><TH className="text-right">Opening</TH><TH className="text-right">Closing</TH><TH className="text-right">Units</TH><TH className="text-right">Amount</TH></TR>
              </THead>
              <TBody>
                {charges.map((c) => (
                  <TR key={c.id}>
                    <TD>{c.period_month}/{c.period_year}</TD>
                    <TD className="text-right tabular-nums text-content-muted">{c.opening_reading ?? "—"}</TD>
                    <TD className="text-right tabular-nums">{c.closing_reading ?? "—"}</TD>
                    <TD className="text-right tabular-nums">{c.units ?? "—"}</TD>
                    <TD className="text-right font-medium tabular-nums">KES {Number(c.amount).toLocaleString()}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          ) : (
            <div className="p-5">
              <Badge tone="neutral">No water charges yet for this unit</Badge>
            </div>
          )}
        </Card>
      )}

      {!tenantId && (
        <EmptyState icon={<Droplets className="h-5 w-5" />} title="Select a unit" description="Pick a unit above to record a reading and see its water charge history." />
      )}
    </div>
  );
}
