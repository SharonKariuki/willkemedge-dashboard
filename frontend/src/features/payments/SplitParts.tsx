/**
 * The parts of one payment shared across tenancies: a tenancy, an amount and
 * the month it pays for on each row, with a running total of what is left to
 * allocate. The form can only save when that reaches exactly zero.
 */
import { Plus, Trash2 } from "lucide-react";

import { TenantPicker } from "@/features/payments/TenantPicker";
import type { TenantChoice } from "@/features/payments/tenantChoices";
import { cn } from "@/lib/cn";

import { type Allocation, centsToAmount, newRow, type SplitRow } from "./splitMath";

const inputCls =
  "w-full rounded-md bg-surface-raised hairline px-3 py-2.5 text-sm text-ink-900 placeholder:text-ink-400 focus:outline-none focus:ring-2 focus:ring-sage-500/40";

const kes = (cents: number) =>
  `KES ${(cents / 100).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 })}`;

export function SplitParts({
  rows,
  onChange,
  choices,
  allocation,
  defaultPeriod,
  disabled,
}: {
  rows: SplitRow[];
  onChange: (rows: SplitRow[]) => void;
  choices: TenantChoice[];
  allocation: Allocation;
  defaultPeriod: { month: number; year: number };
  disabled?: boolean;
}) {
  const update = (key: string, patch: Partial<SplitRow>) =>
    onChange(rows.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  const remove = (key: string) => onChange(rows.filter((r) => r.key !== key));
  const add = () => onChange([...rows, newRow(defaultPeriod.month, defaultPeriod.year)]);

  const { totalCents, allocatedCents, remainingCents } = allocation;
  const balanced = totalCents > 0 && remainingCents === 0;

  return (
    <div className="space-y-3">
      <div className="hidden grid-cols-[minmax(0,1fr)_9rem_5rem_6rem_2rem] gap-2 px-1 text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500 lg:grid">
        <span>Tenancy</span>
        <span>Amount (KES)</span>
        <span>Month</span>
        <span>Year</span>
        <span className="sr-only">Remove</span>
      </div>

      <ol className="space-y-2">
        {rows.map((r, i) => (
          <li
            key={r.key}
            className="grid grid-cols-2 gap-2 rounded-md bg-surface-raised/40 p-2 lg:grid-cols-[minmax(0,1fr)_9rem_5rem_6rem_2rem] lg:items-center lg:bg-transparent lg:p-0"
          >
            <div className="col-span-2 lg:col-span-1">
              <TenantPicker
                choices={choices}
                value={r.tenant}
                onChange={(id) => update(r.key, { tenant: id })}
                disabled={disabled}
                ariaLabel={`Tenancy for part ${i + 1}`}
              />
            </div>
            <div className="col-span-2 flex gap-1 lg:col-span-1">
              <input
                value={r.amount}
                onChange={(e) => update(r.key, { amount: e.target.value })}
                inputMode="decimal"
                placeholder="0.00"
                aria-label={`Amount for part ${i + 1}`}
                className={cn(inputCls, "tabular-nums")}
                disabled={disabled}
              />
            </div>
            <input
              type="number"
              min={1}
              max={12}
              value={r.period_month}
              onChange={(e) => update(r.key, { period_month: Number(e.target.value) })}
              aria-label={`Period month for part ${i + 1}`}
              className={inputCls}
              disabled={disabled}
            />
            <input
              type="number"
              min={2020}
              value={r.period_year}
              onChange={(e) => update(r.key, { period_year: Number(e.target.value) })}
              aria-label={`Period year for part ${i + 1}`}
              className={inputCls}
              disabled={disabled}
            />
            <button
              type="button"
              onClick={() => remove(r.key)}
              disabled={disabled || rows.length <= 2}
              className="col-span-2 justify-self-end rounded p-1.5 text-ink-400 transition-colors hover:bg-danger-soft hover:text-danger disabled:pointer-events-none disabled:opacity-30 lg:col-span-1"
              title={rows.length <= 2 ? "A split needs at least two parts" : "Remove this part"}
              aria-label={`Remove part ${i + 1}`}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </li>
        ))}
      </ol>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={add}
            disabled={disabled}
            className="inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium text-ink-700 glass transition-colors hover:text-ink-900 disabled:opacity-40"
          >
            <Plus className="h-3.5 w-3.5" />
            Add tenancy
          </button>
          {remainingCents > 0 && rows.some((r) => !r.amount.trim()) && (
            <button
              type="button"
              onClick={() => {
                const target = rows.find((r) => !r.amount.trim());
                if (target) update(target.key, { amount: centsToAmount(remainingCents) });
              }}
              disabled={disabled}
              className="inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium text-sage-700 glass transition-colors hover:text-ink-900 disabled:opacity-40"
            >
              Put the remaining {kes(remainingCents)} on the empty part
            </button>
          )}
        </div>
        <p
          className={cn(
            "text-xs tabular-nums",
            balanced ? "text-sage-700 dark:text-sage-400" : "text-ink-500",
          )}
          aria-live="polite"
        >
          Allocated {kes(allocatedCents)} of {kes(totalCents)}
          {totalCents > 0 && remainingCents !== 0 && (
            <span className="ml-1 font-medium text-status-unpaid">
              · {remainingCents > 0 ? `${kes(remainingCents)} left` : `${kes(-remainingCents)} over`}
            </span>
          )}
          {balanced && <span className="ml-1 font-medium">· fully allocated</span>}
        </p>
      </div>
    </div>
  );
}
