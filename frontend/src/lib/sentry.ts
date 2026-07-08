import * as Sentry from "@sentry/react";

/**
 * Initialise Sentry error monitoring.
 *
 * No-op unless VITE_SENTRY_DSN is set, so local/dev builds run without it.
 * Call once, before React renders.
 */
export function initSentry(): void {
  const dsn = import.meta.env.VITE_SENTRY_DSN;
  if (!dsn) return;

  Sentry.init({
    dsn,
    environment: import.meta.env.VITE_SENTRY_ENVIRONMENT ?? import.meta.env.MODE,
    release: import.meta.env.VITE_SENTRY_RELEASE || undefined,
    integrations: [Sentry.browserTracingIntegration()],
    // Performance tracing sampled low to control cost; tune via env.
    tracesSampleRate: Number(import.meta.env.VITE_SENTRY_TRACES_SAMPLE_RATE ?? 0.1),
    // Don't send PII (tenant names, emails) by default.
    sendDefaultPii: false,
  });
}
