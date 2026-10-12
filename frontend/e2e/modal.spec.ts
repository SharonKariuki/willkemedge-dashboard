import { expect, test } from "@playwright/test";

import { hasNoHorizontalScroll, mockApi, seedAuth } from "./helpers";

/**
 * Dialogs must open inside the viewport.
 *
 * The page wrapper keeps a transform after its fade-in, which traps
 * `position: fixed` descendants. A modal rendered in place centred itself on
 * the whole page, so on a long page (tenant detail) it opened off-screen.
 * Runs on the desktop and the 375px mobile project.
 */
const OWNER = {
  id: 1, email: "owner@wilkem.test", username: "owner", first_name: "Wilson",
  last_name: "Osoro", role: "owner", can_record_money: true, can_forgive_money: true,
};

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  await seedAuth(page);
  // Later routes win: an owner (who may void) and one payment to void.
  await page.route("**/api/auth/me/", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify(OWNER) }),
  );
  await page.route("**/api/tenants/1/payment-history/", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        total_paid: "3000.00", total_arrears: "0.00", security_deposit: "0.00",
        monthly_ledger: [], arrears: [],
        payments: [{
          id: 5, amount: "3000.00", payment_date: "2026-10-03", period_month: 10,
          period_year: 2026, source: "mpesa", reference: "UJ3ABC123",
        }],
      }),
    }),
  );
  await page.addInitScript((user) => {
    localStorage.setItem("wk_user", JSON.stringify(user));
  }, OWNER);
});

test("void dialog opens on screen from the tenant page", async ({ page }) => {
  await page.goto("/tenants/1");
  await page.getByRole("button", { name: /Void payment of KES 3000/ }).click();

  const heading = page.getByText("Void payment", { exact: true });
  await expect(heading).toBeInViewport();
  await expect(page.getByLabel("Reason *")).toBeInViewport();
  // The action buttons sit in the footer — they must be reachable too.
  await expect(page.getByRole("button", { name: "Cancel" })).toBeInViewport();
  await expect(await hasNoHorizontalScroll(page)).toBe(true);
});
