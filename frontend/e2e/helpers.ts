import type { Page } from "@playwright/test";

/**
 * Test doubles for the backend. Every `/api/**` request is intercepted:
 * specific endpoints get realistic fixtures, everything else falls back to an
 * empty list / object so pages render their normal (or empty) state without a
 * server.
 */

const USER = { id: 1, email: "owner@wilkem.test", username: "owner", first_name: "Wilson", last_name: "Osoro" };

const DASHBOARD = {
  kpis: {
    total_units: 67, occupied: 60, vacant: 7,
    total_arrears: 452350, collection_received: 320000, collection_expected: 691100,
    collection_percentage: 46, last_month_received: 300000,
  },
  income_trend: [
    { month: "Feb", amount: 280000 }, { month: "Mar", amount: 300000 },
    { month: "Apr", amount: 320000 },
  ],
  occupancy: { paid: 40, partial: 8, unpaid: 12, arrears: 5, vacant: 7 },
  buildings: [{ id: 1, name: "Wilkem Edge Apartments - Donholm", total: 8, occupied: 8, vacant: 0 }],
  recent_payments: [],
  alerts: [],
};

const TENANTS = [
  {
    id: 1, full_name: "Mercy Murunga", first_name: "Mercy", last_name: "Murunga",
    phone: "+254700000001", unit: 1, unit_label: "DON1A",
    building_name: "Wilkem Edge Apartments - Donholm", building_id: 1,
    monthly_rent: "12000.00", deposit_paid: "12000.00", status: "active",
    status_display: "Active", kyc_status: "verified", kyc_status_display: "Verified",
    balance: "0.00", payment_status: "paid", move_in_date: "2026-01-01",
    move_out_date: null, due_day: 5,
  },
];

export async function mockApi(page: Page) {
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/\/api/, "").replace(/\/$/, "");
    const method = route.request().method();

    const json = (body: unknown, status = 200) =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

    if (path === "/auth/login" && method === "POST") {
      return json({ access: "test-access", refresh: "test-refresh", user: USER });
    }
    if (path === "/auth/me") return json(USER);
    if (path === "/auth/logout") return json({});
    if (path === "/dashboard/summary") return json(DASHBOARD);
    if (path === "/tenants" && method === "GET") return json(TENANTS);
    if (path === "/tenants" && method === "POST") return json({ id: 2, ...TENANTS[0] }, 201);
    if (path.startsWith("/tenants/") && path.endsWith("/payment-history")) {
      return json({ total_paid: "120000.00", total_arrears: "0.00", payments: [], arrears: [] });
    }
    if (path.startsWith("/tenants/")) return json(TENANTS[0]);
    if (path === "/buildings") return json(DASHBOARD.buildings.map((b) => ({ ...b, unit_count: b.total, occupied_count: b.occupied })));
    if (path === "/units") return json([]);
    if (path === "/payments" && method === "POST") return json({ id: 1, amount: "12000.00" }, 201);

    // Default: empty list for collection endpoints, empty object otherwise.
    return json(path.endsWith("s") ? [] : {});
  });
}

/** Seed a logged-in session so authenticated pages load directly. */
export async function seedAuth(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("wk_access", "test-access");
    localStorage.setItem("wk_refresh", "test-refresh");
    localStorage.setItem(
      "wk_user",
      JSON.stringify({ id: 1, email: "owner@wilkem.test", username: "owner", first_name: "Wilson", last_name: "Osoro" }),
    );
  });
}

/** True when the page has no horizontal overflow at the current viewport. */
export async function hasNoHorizontalScroll(page: Page): Promise<boolean> {
  return page.evaluate(() => {
    const el = document.documentElement;
    // Allow a 1px rounding tolerance.
    return el.scrollWidth <= el.clientWidth + 1;
  });
}
