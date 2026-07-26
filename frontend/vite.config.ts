import react from "@vitejs/plugin-react";
import path from "node:path";
// defineConfig from vitest/config carries the `test` types, so no triple-slash
// reference directive is needed (and the lint rule forbids one alongside this import).
import { configDefaults, defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          "form-vendor": ["react-hook-form", "@hookform/resolvers", "zod"],
          "query-vendor": ["@tanstack/react-query"],
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    // Playwright owns e2e/*.spec.ts (run via `npm run test:e2e`). Without this,
    // vitest globs those specs and fails to collect them (Playwright's test
    // runtime isn't vitest's), breaking the `npm test` CI gate.
    exclude: [...configDefaults.exclude, "e2e/**"],
  },
});
