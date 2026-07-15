import { defineConfig, devices } from "@playwright/test";

/**
 * E2E config. The app is served as a production build (vite preview); all API
 * calls are intercepted in-test (see e2e/helpers.ts), so no backend is needed.
 *
 * Projects:
 *  - chromium : desktop journey (1280×800)
 *  - mobile   : 375px viewport for the responsive pass
 */
const PORT = 4173;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: "on-first-retry",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 7"], viewport: { width: 375, height: 812 } } },
  ],
  webServer: {
    command: "npm run build && npm run preview",
    url: `http://localhost:${PORT}`,
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
    // The build refuses to run without an API base URL; it is never hit (mocked).
    env: { VITE_API_BASE_URL: "http://localhost:8000/api" },
  },
});
