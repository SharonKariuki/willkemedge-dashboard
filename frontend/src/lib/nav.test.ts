import { describe, expect, it } from "vitest";

import { TABS as ACCOUNTING_TABS } from "@/pages/AccountingPage";
import { TABS as REPORT_TABS } from "@/pages/ReportsPage";

import { DEFAULT_TAB, NAV_ITEMS, NAV_TREE, activePath, isLinkActive, linkHref, links, type NavNode } from "./nav";

const all = links(NAV_TREE);
const tabLinks = (page: "accounting" | "reports") => all.filter((l) => l.page === page);
const covered = (page: "accounting" | "reports") =>
  tabLinks(page).flatMap((l) => l.tab!.covers ?? [l.tab!.value]).sort();

/** Navigation levels: a group adds one, a heading inside a group does not. */
function levels(nodes: NavNode[], d = 1): number {
  return Math.max(
    d,
    ...nodes.map((n) => (n.kind === "link" ? d : levels(n.children, n.kind === "group" ? d + 1 : d)))
  );
}

describe("nav tree", () => {
  it("places every page, and links each page without tabs exactly once", () => {
    const pages = new Set(all.map((l) => l.page));
    expect([...pages].sort()).toEqual(NAV_ITEMS.map((i) => i.key).sort());
    for (const l of all.filter((x) => !x.tab)) expect(all.filter((x) => x.page === l.page)).toHaveLength(1);
  });

  it("uses unique ids", () => {
    const ids: string[] = [];
    const walk = (ns: NavNode[]) =>
      ns.forEach((n) => {
        ids.push(n.id);
        if (n.kind !== "link") walk(n.children);
      });
    walk(NAV_TREE);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("goes three levels deep only through Accounting", () => {
    for (const n of NAV_TREE) expect(levels([n])).toBe(n.id === "finance" ? 3 : n.kind === "group" ? 2 : 1);
  });

  // A tab added to a page without a menu entry (or renamed) would silently
  // drop out of the menu, so the two lists must match exactly.
  it("covers every Accounting tab, each once", () => {
    expect(covered("accounting")).toEqual(ACCOUNTING_TABS.map((t) => t.key).sort());
  });

  it("covers every Reports tab, each once, each category opening its first tab", () => {
    expect(covered("reports")).toEqual(REPORT_TABS.map((t) => t.key).sort());
    for (const l of tabLinks("reports")) expect(l.tab!.value).toBe(l.tab!.covers![0]);
  });

  it("defaults each tabbed page to its first tab", () => {
    expect(DEFAULT_TAB.accounting!.value).toBe(ACCOUNTING_TABS[0].key);
    expect(DEFAULT_TAB.reports!.value).toBe(REPORT_TABS[0].key);
  });

  it("reads the active link and the groups above it from the URL", () => {
    expect(activePath(NAV_TREE, "/accounting", "?acct=ledger")).toEqual(["finance", "accounting", "accounting-ledger"]);
    expect(activePath(NAV_TREE, "/accounting", "")).toEqual(["finance", "accounting", "accounting-balance_sheet"]);
    expect(activePath(NAV_TREE, "/reports", "?tab=aging")).toEqual(["reports", "reports-collections"]);
    expect(activePath(NAV_TREE, "/reports", "?tab=landlord")).toEqual(["reports", "reports-statements"]);
    expect(activePath(NAV_TREE, "/reports", "")).toEqual(["reports", "reports-collections"]);
    expect(activePath(NAV_TREE, "/buildings/12/edit", "")).toEqual(["property", "buildings"]);
    expect(activePath(NAV_TREE, "/dashboard", "")).toEqual(["dashboard"]);
    expect(activePath(NAV_TREE, "/nowhere", "")).toEqual([]);
  });

  it("does not mark a tab link active on another page", () => {
    const ledger = all.find((l) => l.id === "accounting-ledger")!;
    expect(isLinkActive(ledger, "/payments", "?acct=ledger")).toBe(false);
    expect(linkHref(ledger)).toBe("/accounting?acct=ledger");
  });
});
