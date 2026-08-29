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

  test("statements can be emailed to hand-picked tenants", async ({ page }) => {
    await seedAuth(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/tenants");

    // Only Mercy has an email address; Peter's box is disabled, so selecting
    // everyone still resolves to the one tenant who can be written to.
    await page.locator('input[type="checkbox"]:not([disabled])').first().check();
    await expect(page.getByText("1 tenant selected")).toBeVisible();

    await page.getByRole("button", { name: "Email statements" }).click();
    await expect(page.getByText("Email 1 statement")).toBeVisible();
    await expect(page.getByText("mercy.murunga@example.com")).toBeVisible();
    await page.getByRole("button", { name: /send now/i }).click();

    // The bar clears once the send is away.
    await expect(page.getByText("1 tenant selected")).toBeHidden();
  });

  test("a property page emails statements to its current tenants", async ({ page }) => {
    await seedAuth(page);
    await page.goto("/buildings/1");

    // One of the property's two tenants has no address; the button counts who
    // it can actually reach and names the shortfall underneath.
    const send = page.getByRole("button", { name: /Email statements \(1\)/ });
    await expect(send).toBeVisible();
    await expect(page.getByText("1 tenant has no email on file")).toBeVisible();

    await send.click();
    await expect(
      page.getByText(/Every current tenant in Wilkem Edge Apartments - Donholm/),
    ).toBeVisible();
  });
});
