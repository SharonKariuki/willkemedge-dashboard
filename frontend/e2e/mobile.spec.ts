import { expect, test } from "@playwright/test";

import { hasNoHorizontalScroll, mockApi, seedAuth } from "./helpers";

/**
 * Mobile responsive pass — the 375px viewport comes from the "mobile" project
 * (playwright.config.ts). Each key screen must be usable without horizontal
 * scroll. Runs on the desktop project too as a regression guard.
 */
const SCREENS = ["/dashboard", "/tenants", "/income", "/expenses"];

test.describe("Responsive — no horizontal scroll", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page);
    await seedAuth(page);
  });

  test("login page fits the viewport", async ({ page }) => {
    await page.goto("/login");
    await expect(await hasNoHorizontalScroll(page)).toBe(true);
  });

  for (const path of SCREENS) {
    test(`${path} fits the viewport`, async ({ page }) => {
      await page.goto(path);
      // Let charts/layout settle.
      await page.waitForLoadState("networkidle");
      await expect(await hasNoHorizontalScroll(page)).toBe(true);
    });
  }
});
