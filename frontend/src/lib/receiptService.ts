/**
 * receiptService.ts — client-side receipt builder.
 *
 * Builds a display-ready receipt object from a stored ReceiptData response.
 * NEVER recalculates derived values — all amounts come from the stored record.
 *
 * Decoupled from UI: returns a plain object that any renderer can consume
 * (React component, PDF generator, print template, etc.)
 */

import type { ReceiptData } from "./types";
import { formatKES } from "./taxService";

export interface ReceiptLineItem {
  label: string;
  value: string;
  highlight?: boolean; // true for the Total row
}

export interface ReceiptDisplay {
  /** Header info */
  transactionId: string;
  tenantName: string;
  unitLabel: string;
  buildingName: string;
  period: string;          // e.g. "April 2026"
  paymentDate: string | null;
  paymentMode: string;
  referenceCode: string | null;

  /**
   * Financial line items — rendered in order.
   * Composition is determined by show_tax_line / show_total_only flags
   * from the stored ReceiptData. No logic is duplicated here.
   */
  lineItems: ReceiptLineItem[];

  /** Optional fields — null means "do not render". */
  outstandingBalance: string | null;

  /** Classification label for display */
  classificationLabel: string;
}

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

/**
 * Build a ReceiptDisplay from a stored ReceiptData.
 *
 * Rendering contract (mirrors backend receipt_service.py):
 *   show_tax_line  === true  → Base Rent + VAT (16%) + Total (highlighted)
 *   show_total_only === true → Total only (highlighted), no tax line
 */
export function buildReceiptDisplay(data: ReceiptData): ReceiptDisplay {
  const period = `${MONTH_NAMES[data.period_month - 1]} ${data.period_year}`;

  // Build financial line items from stored values — no recalculation.
  const lineItems: ReceiptLineItem[] = [];

  if (data.show_tax_line) {
    // BUSINESS: show breakdown
    lineItems.push({ label: "Base Rent", value: formatKES(data.base_amount) });
    lineItems.push({ label: "VAT (16%)", value: formatKES(data.tax_amount) });
    lineItems.push({
      label: "Total Amount",
      value: formatKES(data.total_amount),
      highlight: true,
    });
  } else {
    // RESIDENTIAL: total only (tax is zero, no line needed)
    lineItems.push({
      label: "Total Amount",
      value: formatKES(data.total_amount),
      highlight: true,
    });
  }

  return {
    transactionId: data.transaction_id,
    tenantName: data.tenant_name,
    unitLabel: data.unit_label,
    buildingName: data.building_name,
    period,
    paymentDate: data.payment_date,
    paymentMode: data.payment_mode,
    referenceCode: data.reference_code || null,
    lineItems,
    outstandingBalance:
      data.outstanding_balance != null
        ? formatKES(data.outstanding_balance)
        : null,
    classificationLabel:
      data.unit_classification === "BUSINESS"
        ? "Business / Commercial"
        : "Residential",
  };
}
