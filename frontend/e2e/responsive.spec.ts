import { expect, test } from "@playwright/test";

import { hasNoHorizontalScroll, mockApi, seedAuth } from "./helpers";

/**
 * Cross-resolution pass. `mobile.spec.ts` pins the 375px phone case; this one
 * sweeps every route across the widths the dashboard is actually opened at —
 * a small phone, a tablet, and the 1366px laptop that is the common desktop.
 *
 * Runs on the desktop project only: the mobile project would repeat the whole
 * sweep for no extra coverage, since each case sets its own viewport.
 */
const ROUTES = [
  "/login", "/dashboard", "/buildings", "/buildings/1", "/units", "/tenants",
  "/tenants/1", "/payments", "/reconciliation", "/expenses", "/income",
  "/water", "/accounting", "/notifications", "/reports", "/settings",
];

const WIDTHS = [360, 768, 1366];

const DESKTOP_ONLY = "the desktop project already covers this sweep";

test.describe("Responsive — every route, every common width", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "chromium", DESKTOP_ONLY);
    await mockApi(page);
    await seedAuth(page);
  });

  for (const width of WIDTHS) {
    test(`no page scrolls sideways at ${width}px`, async ({ page }) => {
      test.setTimeout(180_000);
      await page.setViewportSize({ width, height: 900 });
      for (const path of ROUTES) {
        await page.goto(path);
        await page.waitForLoadState("networkidle").catch(() => {});
        expect(
          await hasNoHorizontalScroll(page),
          `${path} overflows the viewport at ${width}px`
        ).toBe(true);
      }
    });
  }
});

test.describe("Responsive — wide tables scroll instead of crushing", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "chromium", DESKTOP_ONLY);
    await mockApi(page);
    await seedAuth(page);
  });

  /**
   * The tenants table has eleven columns. On a 1366px laptop they do not fit,
   * and the regression is that the browser squeezes them instead: the name
   * ellipsises to "Mercy …" and the building name stacks over four lines while
   * the row still technically "fits". The table must ask for the width its
   * columns need and let its own wrapper scroll.
   */
  test("the tenants table keeps its columns readable at 1366px", async ({ page }) => {
    await page.setViewportSize({ width: 1366, height: 768 });
    await page.goto("/tenants");
    await page.waitForLoadState("networkidle").catch(() => {});

    const measured = await page.evaluate(() => {
      const table = document.querySelector("table")!;
      const wrapper = table.parentElement!;
      const nameCell = table.querySelector("tbody tr td:nth-child(2)") as HTMLElement;
      const buildingCell = table.querySelector("tbody tr td:nth-child(3)") as HTMLElement;
      return {
        tableWidth: table.getBoundingClientRect().width,
        wrapperWidth: wrapper.getBoundingClientRect().width,
        wrapperScrolls: wrapper.scrollWidth > wrapper.clientWidth,
        nameOverflows: nameCell.scrollWidth > nameCell.clientWidth + 1,
        nameHeight: nameCell.getBoundingClientRect().height,
        buildingHeight: buildingCell.getBoundingClientRect().height,
      };
    });

    // The table claims the width its columns need…
    expect(measured.tableWidth).toBeGreaterThan(measured.wrapperWidth);
    // …and the excess stays reachable by scrolling the wrapper, not lost.
    expect(measured.wrapperScrolls).toBe(true);
    // The name is shown in full rather than ellipsised into its neighbour.
    expect(measured.nameOverflows).toBe(false);
    // Nothing wraps onto a second line: a row is one line of text plus padding.
    expect(measured.nameHeight).toBeLessThan(80);
    expect(measured.buildingHeight).toBeLessThan(80);
  });
});
