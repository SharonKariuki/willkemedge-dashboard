import { describe, expect, it } from "vitest";

import {
  TAX_RATE_BUSINESS,
  classificationLabel,
  formatKES,
  previewTax,
} from "./taxService";

describe("previewTax", () => {
  it("applies 16% VAT for BUSINESS units", () => {
    const result = previewTax(10_000, "BUSINESS");
    expect(result.taxRate).toBe(TAX_RATE_BUSINESS);
    expect(result.taxAmount).toBe(1_600);
    expect(result.totalAmount).toBe(11_600);
  });

  it("charges no VAT for RESIDENTIAL units", () => {
    const result = previewTax(10_000, "RESIDENTIAL");
    expect(result.taxRate).toBe(0);
    expect(result.taxAmount).toBe(0);
    expect(result.totalAmount).toBe(10_000);
  });

  it("rounds VAT to 2 decimal places (ROUND_HALF_UP parity)", () => {
    // 1234.567 * 0.16 = 197.53072 -> 197.53
    const result = previewTax(1234.567, "BUSINESS");
    expect(result.taxAmount).toBe(197.53);
  });

  it("rejects non-positive base amounts", () => {
    expect(() => previewTax(0, "BUSINESS")).toThrow();
    expect(() => previewTax(-50, "RESIDENTIAL")).toThrow();
  });
});

describe("classificationLabel", () => {
  it("labels each classification", () => {
    expect(classificationLabel("BUSINESS")).toBe("Business / Commercial");
    expect(classificationLabel("RESIDENTIAL")).toBe("Residential");
  });
});

describe("formatKES", () => {
  it("formats with KES prefix and two decimals", () => {
    expect(formatKES(16000)).toBe("KES 16,000.00");
    expect(formatKES("1500.5")).toBe("KES 1,500.50");
  });
});
