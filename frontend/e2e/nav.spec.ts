import { expect, test } from "@playwright/test";

import { mockApi, seedAuth } from "./helpers";

/**
 * The menu tree. Every page must be reachable at every width: the sidebar on
 * desktop, the icon rail's flyouts on a tablet, and the Menu sheet on a phone
 * (which once missed four pages because it kept its own list).
 */
const PAGES = [
  "/dashboard", "/buildings", "/units", "/tenants", "/payments", "/reconciliation",
  "/water", "/income", "/expenses", "/accounting", "/reports", "/notifications", "/settings",
];

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  await seedAuth(page);
});

test("the phone menu reaches every page, and opens Reports into its views", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/dashboard");
  await page.getByRole("button", { name: "Menu", exact: true }).click();

  const sheet = page.getByRole("dialog", { name: "Menu" });
  await expect(sheet).toBeVisible();
  await expect(sheet.getByRole("button", { name: "Sign out" })).toBeVisible();

  for (const path of PAGES.filter((p) => p !== "/accounting" && p !== "/reports")) {
    await expect(sheet.locator(`a[href="${path}"]`), `${path} missing from the phone menu`).toHaveCount(1);
  }

  await sheet.getByRole("button", { name: "Reports" }).click();
  await sheet.getByRole("link", { name: "Aging Balances" }).click();

  await expect(page).toHaveURL(/\/reports\?tab=aging$/);
  await expect(sheet).toBeHidden();
});

test("a sidebar child opens its tab and is marked as the current page", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "chromium", "the sidebar is hidden on the phone viewport");
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/dashboard");

  const nav = page.getByRole("navigation", { name: "Main" });
  const accounting = nav.getByRole("button", { name: "Accounting" });
  await accounting.click();
  await expect(accounting).toHaveAttribute("aria-expanded", "true");

  await nav.getByRole("link", { name: "Trial Balance" }).click();
  await expect(page).toHaveURL(/\/accounting\?acct=trial_balance$/);
  await expect(nav.getByRole("link", { name: "Trial Balance" })).toHaveAttribute("aria-current", "page");
  await expect(nav.getByRole("link", { name: "Balance Sheet" })).not.toHaveAttribute("aria-current", "page");
});

test("on the icon rail a parent opens a flyout with its views", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "chromium", "the rail is hidden on the phone viewport");
  await page.setViewportSize({ width: 900, height: 800 });
  await page.goto("/dashboard");

  await page.getByRole("button", { name: "Reports" }).click();
  const flyout = page.getByRole("navigation", { name: "Reports" });
  await expect(flyout).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(flyout).toBeHidden();

  await page.getByRole("button", { name: "Reports" }).click();
  await flyout.getByRole("link", { name: "Landlord Statement" }).click();
  await expect(page).toHaveURL(/\/reports\?tab=landlord$/);
  await expect(flyout).toBeHidden();
});
