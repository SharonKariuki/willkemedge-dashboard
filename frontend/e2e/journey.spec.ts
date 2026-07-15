import { expect, test } from "@playwright/test";

import { mockApi, seedAuth } from "./helpers";

test.describe("Core journey", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page);
  });

  test("login lands on the dashboard", async ({ page }) => {
    await page.goto("/login");
    await page.getByPlaceholder("you@clinic.com").fill("owner@wilkem.test");
    await page.locator('input[type="password"]').fill("secret-password");
    await page.getByRole("button", { name: /sign in/i }).click();

    await expect(page).toHaveURL(/\/dashboard/);
  });

  test("dashboard exposes the journey entry points", async ({ page }) => {
    await seedAuth(page);
    await page.goto("/dashboard");

    // The journey's core actions are reachable from the dashboard.
    await expect(page.getByRole("link", { name: /add tenant/i })).toBeVisible();
    await expect(page.getByRole("link", { name: /record payment/i })).toBeVisible();
    await expect(page.getByRole("link", { name: /view reports/i })).toBeVisible();
  });

  test("tenant list renders records", async ({ page }) => {
    await seedAuth(page);
    await page.goto("/tenants");
    // The name renders in both the desktop table and the mobile card list; one
    // is always hidden by the responsive layout, so assert it's in the DOM.
    await expect(page.getByText("Mercy Murunga").first()).toBeAttached();
  });

  test("register-tenant form opens from the tenants page", async ({ page }) => {
    await seedAuth(page);
    await page.goto("/tenants?new=1");
    // The register form is opened via the URL param (dashboard "Add tenant").
    await expect(page.getByText(/new tenant/i)).toBeVisible();
  });
});
