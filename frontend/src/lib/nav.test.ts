import { describe, expect, it } from "vitest";

import { TABS as ACCOUNTING_TABS } from "@/pages/AccountingPage";
import { TABS as REPORT_TABS } from "@/pages/ReportsPage";

import { NAV_CHILDREN, NAV_FOOTER, NAV_ITEMS, NAV_SECTIONS, isChildActive, navItem } from "./nav";

const childValues = (key: "accounting" | "reports") =>
  NAV_CHILDREN[key]!.flatMap((g) => g.items.map((c) => c.value)).sort();

describe("nav tree", () => {
  it("places every page exactly once", () => {
    const placed = [...NAV_SECTIONS.flatMap((s) => s.keys), ...NAV_FOOTER];
    expect(placed.slice().sort()).toEqual(NAV_ITEMS.map((i) => i.key).sort());
  });

  // A tab added to a page without a menu entry (or renamed) would silently
  // drop out of the menu, so the two lists must match exactly.
  it("lists every Accounting tab, and only those", () => {
    expect(childValues("accounting")).toEqual(ACCOUNTING_TABS.map((t) => t.key).sort());
  });

  it("lists every Reports tab, and only those", () => {
    expect(childValues("reports")).toEqual(REPORT_TABS.map((t) => t.key).sort());
  });

  it("treats a page with no tab in its URL as showing its first child", () => {
    const reports = navItem("reports");
    const [first, second] = NAV_CHILDREN.reports![0].items;
    expect(isChildActive(reports, first, "/reports", "")).toBe(true);
    expect(isChildActive(reports, second, "/reports", "")).toBe(false);
    expect(isChildActive(reports, second, "/reports", `?tab=${second.value}`)).toBe(true);
    expect(isChildActive(reports, second, "/payments", `?tab=${second.value}`)).toBe(false);
  });
});
