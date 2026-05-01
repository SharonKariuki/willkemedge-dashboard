/**
 * taxService.ts — frontend mirror of backend tax_service.py
 *
 * Single source of truth for tax display logic on the client side.
 * Used by forms (to preview totals before submission) and by any
 * component that needs to format tax-related values.
 *
 * IMPORTANT: Receipt components must use stored ReceiptData values
 * from the API — not recalculate them here. This utility is for
 * live form previews only.
 */

import type { UnitClassification } from "./types";

export const TAX_RATE_BUSINESS = 0.16;
export const TAX_RATE_RESIDENTIAL = 0.0;

export interface TaxPreview {
  classification: UnitClassification;
  baseAmount: number;
  taxRate: number;
  taxAmount: number;
  totalAmount: number;
}

/**
 * Compute a tax preview for a given base amount and unit classification.
 * Round tax to 2 decimal places (matching backend ROUND_HALF_UP).
 */
export function previewTax(
  baseAmount: number,
  classification: UnitClassification,
): TaxPreview {
  if (baseAmount <= 0) {
    throw new Error(`baseAmount must be positive, got ${baseAmount}`);
  }

  const taxRate =
    classification === "BUSINESS" ? TAX_RATE_BUSINESS : TAX_RATE_RESIDENTIAL;

  const taxAmount = Math.round(baseAmount * taxRate * 100) / 100;
  const totalAmount = baseAmount + taxAmount;

  return { classification, baseAmount, taxRate, taxAmount, totalAmount };
}

/** Human-readable label for a classification value. */
export function classificationLabel(classification: UnitClassification): string {
  return classification === "BUSINESS" ? "Business / Commercial" : "Residential";
}

/** Format KES amount for display (e.g. "KES 16,000.00"). */
export function formatKES(amount: number | string): string {
  return `KES ${Number(amount).toLocaleString("en-KE", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}
