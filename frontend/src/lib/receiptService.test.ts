import { describe, expect, it } from "vitest";

import { buildReceiptDisplay } from "./receiptService";
import type { ReceiptData } from "./types";

function makeReceipt(overrides: Partial<ReceiptData> = {}): ReceiptData {
  return {
    transaction_id: "TXN-001",
    reference_code: "MP1234ABCD",
    payment_mode: "MPESA",
    tenant_name: "Jane Doe",
    unit_label: "A1",
    building_name: "Maple Court",
    period_month: 4,
    period_year: 2026,
    payment_date: "2026-04-10",
    unit_classification: "RESIDENTIAL",
    base_amount: "10000.00",
    tax_amount: "0.00",
    total_amount: "10000.00",
    show_tax_line: false,
    show_total_only: true,
    outstanding_balance: null,
    ...overrides,
  };
}

describe("buildReceiptDisplay", () => {
  it("formats the period as month name and year", () => {
    const display = buildReceiptDisplay(makeReceipt());
    expect(display.period).toBe("April 2026");
  });

  it("renders a single total line for residential receipts", () => {
    const display = buildReceiptDisplay(makeReceipt());
    expect(display.lineItems).toHaveLength(1);
    expect(display.lineItems[0]).toMatchObject({
      label: "Total Amount",
      value: "KES 10,000.00",
      highlight: true,
    });
  });

  it("renders base + VAT + total for business receipts using stored values", () => {
    const display = buildReceiptDisplay(
      makeReceipt({
        unit_classification: "BUSINESS",
        base_amount: "10000.00",
        tax_amount: "1600.00",
        total_amount: "11600.00",
        show_tax_line: true,
        show_total_only: false,
      }),
    );
    expect(display.lineItems.map((l) => l.label)).toEqual([
      "Base Rent",
      "VAT (16%)",
      "Total Amount",
    ]);
    expect(display.lineItems[1].value).toBe("KES 1,600.00");
    expect(display.lineItems[2]).toMatchObject({ value: "KES 11,600.00", highlight: true });
    expect(display.classificationLabel).toBe("Business / Commercial");
  });

  it("nulls reference and outstanding balance when absent", () => {
    const display = buildReceiptDisplay(makeReceipt({ reference_code: "", outstanding_balance: null }));
    expect(display.referenceCode).toBeNull();
    expect(display.outstandingBalance).toBeNull();
  });

  it("formats an outstanding balance when present", () => {
    const display = buildReceiptDisplay(makeReceipt({ outstanding_balance: "2500" }));
    expect(display.outstandingBalance).toBe("KES 2,500.00");
  });

  it("formats a credit outstanding balance with a 'cr' suffix, not a minus sign", () => {
    const display = buildReceiptDisplay(makeReceipt({ outstanding_balance: "-1500" }));
    expect(display.outstandingBalance).toBe("KES 1,500.00 cr");
  });
});
