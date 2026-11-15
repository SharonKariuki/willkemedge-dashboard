import { describe, expect, it } from "vitest";

import { allocate, centsToAmount, newRow, type SplitRow, toCents } from "./splitMath";

const row = (tenant: number | null, amount: string): SplitRow => ({
  ...newRow(11, 2026),
  tenant,
  amount,
});

describe("toCents", () => {
  it("reads commas and decimals", () => {
    expect(toCents("205,500.50")).toBe(20550050);
    expect(toCents("0.1")).toBe(10);
  });
  it("is null for blank or junk", () => {
    expect(toCents("")).toBeNull();
    expect(toCents("abc")).toBeNull();
  });
});

describe("allocate", () => {
  it("is ready when the parts add up to the cheque exactly", () => {
    const a = allocate("205,500", [row(1, "123540"), row(2, "81960")]);
    expect(a.remainingCents).toBe(0);
    expect(a.problems).toEqual([]);
  });

  it("does not trip on floating point", () => {
    expect(allocate("0.3", [row(1, "0.1"), row(2, "0.2")]).problems).toEqual([]);
  });

  it("says how much is left to allocate", () => {
    const a = allocate("205500", [row(1, "123540"), row(2, "80000")]);
    expect(a.remainingCents).toBe(196000);
    expect(a.problems).toContain(`KES ${centsToAmount(196000)} still to allocate.`);
  });

  it("says when more is allocated than received", () => {
    const a = allocate("100", [row(1, "60"), row(2, "50")]);
    expect(a.problems).toContain("Allocated KES 10.00 more than was received.");
  });

  it("needs two parts, a tenancy and an amount on each", () => {
    expect(allocate("100", [row(1, "100")]).problems).toContain("Split across at least two tenancies.");
    expect(allocate("100", [row(null, "50"), row(2, "50")]).problems).toContain(
      "Choose a tenancy for every part.",
    );
    expect(allocate("100", [row(1, ""), row(2, "100")]).problems).toContain("Every part needs an amount.");
  });
});
