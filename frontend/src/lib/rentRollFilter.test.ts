import { describe, expect, it } from "vitest";

import {
  filterByMonth, filterRentRoll, monthOfIsoDate, parseRentRollFilter, rowMonthValue,
} from "./rentRollFilter";

const row = (period_year: number, period_month: number) => ({ period_year, period_month });

// Jan 2025 → Oct 2026: runs a month past "today" (a tenant paid ahead).
const ROWS = Array.from({ length: 22 }, (_, i) => row(2025 + Math.floor(i / 12), (i % 12) + 1));
const TODAY = new Date(2026, 8, 24); // 24 Sept 2026
const months = (rows: { period_year: number; period_month: number }[]) => rows.map(rowMonthValue);

describe("parseRentRollFilter", () => {
  it("keeps presets, 'all' and real months", () => {
    for (const v of ["1m", "3m", "12m", "all", "2026-08"]) expect(parseRentRollFilter(v)).toBe(v);
  });

  it("falls back to the last three months for anything else", () => {
    for (const v of [null, undefined, "", "6m", "2026-13", "2026-8", "august"]) {
      expect(parseRentRollFilter(v)).toBe("3m");
    }
  });
});

describe("filterRentRoll", () => {
  it("defaults to this month and the two before, keeping rows paid ahead", () => {
    expect(months(filterRentRoll(ROWS, "3m", TODAY))).toEqual(["2026-07", "2026-08", "2026-09", "2026-10"]);
  });

  it("past month is this month onward", () => {
    expect(months(filterRentRoll(ROWS, "1m", TODAY))).toEqual(["2026-09", "2026-10"]);
  });

  it("past year spans twelve calendar months across the year boundary", () => {
    const kept = months(filterRentRoll(ROWS, "12m", TODAY));
    expect(kept[0]).toBe("2025-10");
    expect(kept).toHaveLength(13);
  });

  it("a single month keeps only that month", () => {
    expect(months(filterRentRoll(ROWS, "2025-08", TODAY))).toEqual(["2025-08"]);
    expect(filterRentRoll(ROWS, "2024-08", TODAY)).toEqual([]);
  });

  it("'all' returns the roll untouched", () => {
    expect(filterRentRoll(ROWS, "all", TODAY)).toBe(ROWS);
  });
});

describe("filterByMonth — payment history, by the date money arrived", () => {
  // A payment received in October but booked to the July rent period.
  const PAYMENTS = [
    { id: 1, payment_date: "2026-10-03", period_year: 2026, period_month: 7 },
    { id: 2, payment_date: "2026-09-26", period_year: 2026, period_month: 7 },
    { id: 3, payment_date: "2026-05-11", period_year: 2026, period_month: 5 },
  ];
  const byDate = (p: { payment_date: string }) => monthOfIsoDate(p.payment_date);
  const ids = (rows: { id: number }[]) => rows.map((r) => r.id);
  const OCT = new Date(2026, 9, 17);

  it("windows on the payment date, not the rent period", () => {
    expect(ids(filterByMonth(PAYMENTS, "1m", byDate, OCT))).toEqual([1]);
    expect(ids(filterByMonth(PAYMENTS, "3m", byDate, OCT))).toEqual([1, 2]);
  });

  it("picks one month, and 'all' keeps everything", () => {
    expect(ids(filterByMonth(PAYMENTS, "2026-09", byDate, OCT))).toEqual([2]);
    expect(ids(filterByMonth(PAYMENTS, "2026-07", byDate, OCT))).toEqual([]);
    expect(ids(filterByMonth(PAYMENTS, "all", byDate, OCT))).toEqual([1, 2, 3]);
  });
});
