import { describe, expect, it } from "vitest";

import { isNonNegativeAmountOrBlank, isPositiveAmount } from "./formValidators";

describe("isPositiveAmount", () => {
  it("accepts a plain positive number string", () => {
    expect(isPositiveAmount("12000")).toBe(true);
    expect(isPositiveAmount("0.5")).toBe(true);
  });

  it("rejects zero, negatives, blanks and non-numeric input", () => {
    expect(isPositiveAmount("0")).toBe(false);
    expect(isPositiveAmount("-100")).toBe(false);
    expect(isPositiveAmount("")).toBe(false);
    expect(isPositiveAmount("abc")).toBe(false);
  });

  it("rejects thousands-separated input (Number('12,000') is NaN)", () => {
    expect(isPositiveAmount("12,000")).toBe(false);
  });
});

describe("isNonNegativeAmountOrBlank", () => {
  it("treats blank / null / undefined as valid (optional field)", () => {
    expect(isNonNegativeAmountOrBlank("")).toBe(true);
    expect(isNonNegativeAmountOrBlank(undefined)).toBe(true);
    expect(isNonNegativeAmountOrBlank(null)).toBe(true);
  });

  it("accepts zero and positive amounts", () => {
    expect(isNonNegativeAmountOrBlank("0")).toBe(true);
    expect(isNonNegativeAmountOrBlank("5000")).toBe(true);
  });

  it("rejects negatives and non-numeric input", () => {
    expect(isNonNegativeAmountOrBlank("-1")).toBe(false);
    expect(isNonNegativeAmountOrBlank("abc")).toBe(false);
    expect(isNonNegativeAmountOrBlank("1,000")).toBe(false);
  });
});
