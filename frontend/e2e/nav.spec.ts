import { expect, test, type Page } from "@playwright/test";

import { mockApi, seedAuth } from "./helpers";

/**
 * The menu tree. Every page must be reachable at every width — the sidebar on
 * desktop, the icon rail's flyouts on a tablet, the drawer on a phone — and
 * which item is current must come from the URL alone.
 */
const PAGES = [
  "/dashboard", "/buildings", "/units", "/tenants", "/water", "/payments", "/reconciliation",
  "/income", "/expenses", "/notifications", "/settings",
];
const TAB_LINKS = [
  "/accounting?acct=balance_sheet", "/accounting?acct=pnl", "/accounting?acct=trial_balance",
  "/accounting?acct=ledger", "/accounting?acct=coa", "/accounting?acct=petty_cash", "/accounting?acct=budgeting",
  "/reports?tab=monthly", "/reports?tab=occupancy", "/reports?tab=tenant_stmt", "/reports?tab=pnl",
];

const desktopOnly = (name: string) => test.skip(name !== "chromium", "the sidebar is hidden on the phone viewport");

/** Signs in as the owner: the only role that sees the Activity Log. */
async function asOwner(page: Page) {
  const owner = { id: 1, email: "owner@wilkem.test", username: "owner", can_forgive_money: true };
  await page.route("**/api/auth/me**", (r) =>
    r.fulfill({ contentType: "application/json", body: JSON.stringify(owner) })
  );
  await page.addInitScript((u) => localStorage.setItem("wk_user", JSON.stringify(u)), owner);
}

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  await seedAuth(page);
});

test("the phone drawer reaches every page and closes once one is chosen", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/dashboard");
  await page.getByRole("button", { name: "Menu", exact: true }).click();

  const drawer = page.getByRole("dialog", { name: "Menu" });
  await expect(drawer).toBeVisible();
  await expect(drawer.getByRole("button", { name: "Sign out" })).toBeVisible();

  // Open every folded section, Accounting included.
  for (let folded = drawer.locator('button[aria-expanded="false"]'); await folded.count(); ) {
    await folded.first().click();
  }
  for (const href of [...PAGES, ...TAB_LINKS]) {
    await expect(drawer.locator(`a[href="${href}"]`), `${href} missing from the drawer`).toHaveCount(1);
  }
  // Not the owner: no Activity Log.
  await expect(drawer.locator('a[href="/activity"]')).toHaveCount(0);

  await drawer.getByRole("link", { name: "Tenant Statements" }).click();
  await expect(page).toHaveURL(/\/reports\?tab=tenant_stmt$/);
  await expect(drawer).toBeHidden();
});

test("Accounting's third level opens its tab and marks it current", async ({ page }, info) => {
  desktopOnly(info.project.name);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/dashboard");

  const nav = page.getByRole("navigation", { name: "Main" });
  await nav.getByRole("button", { name: "Finance" }).click();
  await nav.getByRole("button", { name: "Accounting" }).click();
  await expect(nav.getByText("Financial Statements")).toBeVisible();
  await expect(nav.getByText("Books & Controls")).toBeVisible();

  await nav.getByRole("link", { name: "Trial Balance" }).click();
  await expect(page).toHaveURL(/\/accounting\?acct=trial_balance$/);
  await expect(nav.getByRole("link", { name: "Trial Balance" })).toHaveAttribute("aria-current", "page");
  await expect(nav.getByRole("link", { name: "Balance Sheet" })).not.toHaveAttribute("aria-current", "page");
});

test("a direct URL opens only the sections above it, and survives a refresh", async ({ page }, info) => {
  desktopOnly(info.project.name);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/reports?tab=landlord");

  const nav = page.getByRole("navigation", { name: "Main" });
  await expect(nav.getByRole("button", { name: "Reports" })).toHaveAttribute("aria-expanded", "true");
  await expect(nav.getByRole("button", { name: "Property Management" })).toHaveAttribute("aria-expanded", "false");
  await expect(nav.getByRole("link", { name: "Tenant Statements" })).toHaveAttribute("aria-current", "page");

  await page.reload();
  await expect(nav.getByRole("link", { name: "Tenant Statements" })).toHaveAttribute("aria-current", "page");
});

test("back and forward move the current item with the page", async ({ page }, info) => {
  desktopOnly(info.project.name);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/dashboard");

  const nav = page.getByRole("navigation", { name: "Main" });
  await nav.getByRole("button", { name: "Property Management" }).click();
  await nav.getByRole("link", { name: "Units" }).click();
  await nav.getByRole("link", { name: "Properties" }).click();
  await expect(nav.getByRole("link", { name: "Properties" })).toHaveAttribute("aria-current", "page");

  await page.goBack();
  await expect(page).toHaveURL(/\/units$/);
  await expect(nav.getByRole("link", { name: "Units" })).toHaveAttribute("aria-current", "page");
  await page.goForward();
  await expect(nav.getByRole("link", { name: "Properties" })).toHaveAttribute("aria-current", "page");
});

test("sections open and close by hand, and stay that way across visits", async ({ page }, info) => {
  desktopOnly(info.project.name);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/dashboard");

  const nav = page.getByRole("navigation", { name: "Main" });
  const comms = nav.getByRole("button", { name: "Communications" });
  await comms.click();
  await expect(comms).toHaveAttribute("aria-expanded", "true");
  await expect(nav.getByRole("link", { name: "Notifications" })).toBeVisible();

  await page.reload();
  await expect(comms).toHaveAttribute("aria-expanded", "true");

  await comms.click();
  await expect(comms).toHaveAttribute("aria-expanded", "false");
  await expect(nav.getByRole("link", { name: "Notifications" })).toBeHidden();
});

test("the owner sees the Activity Log; a section with every page hidden disappears", async ({ page }, info) => {
  desktopOnly(info.project.name);
  await asOwner(page);
  await page.addInitScript(() =>
    localStorage.setItem("willkemedge-view-prefs", JSON.stringify({ notifications: false }))
  );
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/dashboard");

  const nav = page.getByRole("navigation", { name: "Main" });
  await nav.getByRole("button", { name: "Administration" }).click();
  await nav.getByRole("link", { name: "Activity Log" }).click();
  await expect(page).toHaveURL(/\/activity$/);
  await expect(nav.getByRole("link", { name: "Activity Log" })).toHaveAttribute("aria-current", "page");

  await expect(nav.getByRole("button", { name: "Communications" })).toHaveCount(0);
});

test("on the icon rail a section opens a flyout with its pages", async ({ page }, info) => {
  desktopOnly(info.project.name);
  await page.setViewportSize({ width: 900, height: 800 });
  await page.goto("/dashboard");

  await page.getByRole("button", { name: "Reports" }).click();
  const flyout = page.getByRole("navigation", { name: "Reports" });
  await expect(flyout).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(flyout).toBeHidden();

  await page.getByRole("button", { name: "Reports" }).click();
  await flyout.getByRole("link", { name: "Occupancy" }).click();
  await expect(page).toHaveURL(/\/reports\?tab=occupancy$/);
  await expect(flyout).toBeHidden();
});

test("below lg the expand button floats the full sidebar over the page", async ({ page }, info) => {
  desktopOnly(info.project.name);
  await page.setViewportSize({ width: 900, height: 800 });
  await page.goto("/dashboard");

  await page.getByRole("button", { name: "Expand sidebar" }).click();
  const nav = page.getByRole("navigation", { name: "Main" });
  await expect(nav.getByRole("button", { name: "Property Management" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "Expand sidebar" })).toBeVisible();

  await page.getByRole("button", { name: "Expand sidebar" }).click();
  await nav.getByRole("button", { name: "Property Management" }).click();
  await nav.getByRole("link", { name: "Tenants" }).click();
  await expect(page).toHaveURL(/\/tenants$/);
  await expect(page.getByRole("button", { name: "Expand sidebar" })).toBeVisible();
});

test("moving through the menu logs no errors", async ({ page }, info) => {
  desktopOnly(info.project.name);
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));

  await page.setViewportSize({ width: 1440, height: 900 });
  for (const href of [...PAGES, ...TAB_LINKS]) {
    await page.goto(href);
    await expect(page.getByRole("navigation", { name: "Main" }).locator('[aria-current="page"]')).toHaveCount(1);
  }
  expect(errors).toEqual([]);
});
