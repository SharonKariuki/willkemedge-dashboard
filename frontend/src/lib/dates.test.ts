import { describe, expect, it } from "vitest";
import { fromDayFirst, maskDayFirst, toDayFirst } from "@/lib/dates";

describe("fromDayFirst", () => {
  it("reads the date the landlord could not enter", () => {
    // The whole reason this module exists: 1 October 2026, as he typed it.
    expect(fromDayFirst("01-10-2026")).toBe("2026-10-01");
  });

  it.each([
    ["01/10/2026", "2026-10-01"],
    ["01-10-2026", "2026-10-01"],
    ["01.10.2026", "2026-10-01"],
    ["01 10 2026", "2026-10-01"],
    ["01102026", "2026-10-01"],
    ["1/10/2026", "2026-10-01"],
  ])("accepts %s however it was punctuated", (typed, iso) => {
    expect(fromDayFirst(typed)).toBe(iso);
  });

  it("is day-first, not month-first", () => {
    // The half of the bug that was silent: month-first would read this as
    // 10 January and store it without complaint.
    expect(fromDayFirst("01/10/2026")).toBe("2026-10-01");
    expect(fromDayFirst("13/10/2026")).toBe("2026-10-13");
    expect(fromDayFirst("10/13/2026")).toBe("");
  });

  it("passes ISO through, so a paste and a form default both work", () => {
    expect(fromDayFirst("2026-10-01")).toBe("2026-10-01");
  });

  it.each(["31/02/2026", "31/04/2026", "29/02/2027", "00/10/2026", "01/13/2026"])(
    "rejects %s — not a day that exists",
    (typed) => expect(fromDayFirst(typed)).toBe(""),
  );

  it.each(["", "   ", "01", "01/", "01/10", "next Tuesday", "2026-13-01"])(
    "returns nothing for %s rather than guessing",
    (typed) => expect(fromDayFirst(typed)).toBe(""),
  );

  it("wants all four digits of the year", () => {
    // 01/10/20 is not 2020 — it is someone two keystrokes from finishing
    // 01/10/2026, and billing dates are not the place to guess which.
    expect(fromDayFirst("01/10/20")).toBe("");
    expect(fromDayFirst("01/10/2026")).toBe("2026-10-01");
  });

  it("treats a part-typed date as unfinished, not as wrong", () => {
    // A required-field check reads "" as "not filled in yet", so the box does
    // not go red between the first keystroke and the last.
    for (const partial of ["0", "01", "01/1", "01/10", "01/10/2"]) {
      expect(fromDayFirst(partial)).toBe("");
    }
    expect(fromDayFirst("01/10/2026")).toBe("2026-10-01");
  });
});

describe("toDayFirst", () => {
  it("shows a stored date the way it is written here", () => {
    expect(toDayFirst("2026-10-01")).toBe("01/10/2026");
  });

  it.each([null, undefined, "", "not a date", "01/10/2026"])(
    "renders %s as empty rather than as itself",
    (value) => expect(toDayFirst(value)).toBe(""),
  );

  it("round-trips with fromDayFirst", () => {
    for (const iso of ["2026-10-01", "2026-01-10", "2026-12-31", "2024-02-29"]) {
      expect(fromDayFirst(toDayFirst(iso))).toBe(iso);
    }
  });
});

describe("maskDayFirst", () => {
  it.each([
    ["0", "0"],
    ["01", "01"],
    ["011", "01/1"],
    ["0110", "01/10"],
    ["01102026", "01/10/2026"],
    ["01-10-2026", "01/10/2026"],
  ])("tidies %s into %s as it is typed", (raw, masked) => {
    expect(maskDayFirst(raw)).toBe(masked);
  });

  it("lets a slash be deleted instead of putting it straight back", () => {
    // Backspacing "01/" leaves "01" — if the mask re-added the slash the
    // cursor could never get back past it.
    expect(maskDayFirst("01")).toBe("01");
  });

  it("stops at eight digits", () => {
    expect(maskDayFirst("011020261234")).toBe("01/10/2026");
  });

  it("leaves a date on its way to ISO alone", () => {
    // Masking a pasted 2026-10-01 into 20/26/1001 would be worse than nothing.
    expect(maskDayFirst("2026-10-01")).toBe("2026-10-01");
    expect(maskDayFirst("2026-1")).toBe("2026-1");
  });
});
