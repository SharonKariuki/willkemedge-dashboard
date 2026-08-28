/**
 * Tenant options for the reconciliation picker.
 *
 * Split from the component so the module exports components only and Vite's
 * fast refresh keeps working.
 */
import type { TenantListItem } from "@/lib/types";

export interface TenantChoice {
  id: number;
  unitLabel: string;
  name: string;
  phone: string;
  status: TenantListItem["status"];
  statusDisplay: string;
}

/** Active first, then by unit — the order someone reading a bank narration scans in. */
const STATUS_ORDER: Record<string, number> = {
  active: 0,
  notice_given: 1,
  moved_out: 2,
  archived: 3,
};

export function toChoices(tenants: TenantListItem[] | undefined): TenantChoice[] {
  return [...(tenants ?? [])]
    .map((t) => ({
      id: t.id,
      unitLabel: t.unit_label ?? "",
      name: t.full_name,
      phone: t.phone ?? "",
      status: t.status,
      statusDisplay: t.status_display,
    }))
    .sort((a, b) => {
      const byStatus = (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9);
      return byStatus !== 0 ? byStatus : a.unitLabel.localeCompare(b.unitLabel);
    });
}

/** Digits only, so "0720 772330" matches a narration carrying "254720772330". */
const digits = (s: string) => s.replace(/\D/g, "");

export function matches(choice: TenantChoice, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  const haystack = `${choice.unitLabel} ${choice.name}`.toLowerCase();
  if (haystack.includes(q)) return true;
  const qDigits = digits(q);
  return qDigits.length >= 3 && digits(choice.phone).includes(qDigits);
}

