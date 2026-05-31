# QA System Audit — Wilkem Edge Rental Management Dashboard

**Prepared by:** QA Engineering
**Date:** 2026-05-23
**Branch audited:** `feat/fixes` (clean working tree)
**System:** Django REST backend (~9.3k LOC) + React/TS/Vite frontend (~9.8k LOC)
**Method:** Static code review (file:line evidence), backend test-suite execution, CI/CD inspection.

---

## 1. Executive summary

The system is **functionally mature** — auth, tenants, units, payments, arrears, reporting, SMS/email, and PDF statements all exist and the backend test suite is green (**91 tests pass in ~97s**). Production Django settings are genuinely well-hardened.

However, this audit found **defects that put financial integrity and sensitive data at risk**, plus a structural quality gap: **the money-handling reporting layer and the entire frontend have no automated tests**, and the frontend CI has no test gate at all.

**Verdict:** Not yet Go-Live ready from a QA standpoint. There are 3 CRITICAL and 5 HIGH issues, several touching money or PII, that should be fixed and locked behind tests before production cutover. The M-Pesa integration is independently blocked on Co-op Bank (administrative, tracked separately in `MPESA_STATUS_REPORT.md`).

### Severity tally

| Severity | Count | Theme |
|---|---|---|
| CRITICAL | 3 | Exposed secrets, payment double-processing, client-trusted webhook amounts |
| HIGH | 5 | Wrong-tenant credit, broken STK push, no IDOR scoping, unprotected KYC docs, no fetch-error UX |
| MEDIUM | ~12 | Arrears/waiver bug, float money math, file-upload trust, a11y, lockout DoS, lost-funds path |
| LOW | ~11 | Dead code, stale comments, unbounded tables, config fallbacks |

---

## 2. Test & CI coverage gaps (the headline QA finding)

| Area | Test files | Status |
|---|---|---|
| backend `accounts` | 3 | Covered |
| backend `payments` | 4 | Covered |
| backend `buildings` | 1 | Covered |
| backend `tenants` | 1 | Covered |
| **backend `dashboard` (780 LOC, incl. 514 LOC financial reports)** | **0** | **No tests** |
| **backend `expenses`** | **0** | **No tests** |
| **frontend (entire app, 13 pages / 12 hooks)** | **0** | **No tests** |

- **Reporting is untested.** `apps/dashboard/views_reports.py` (514 LOC) computes the financial reports Dr. Osoro relies on daily — none are covered by a test. A regression here is invisible until the owner reads a wrong number.
- **Frontend has a configured runner but zero tests.** `vitest` + `"test": "vitest run"` exist in `frontend/package.json:12,54`, but there are 0 test files and no `test` block in `vite.config.ts`. A money app ships with no client regression net.
- **Frontend CI has no test step**, and lint is **non-blocking**: `.github/workflows/frontend-ci.yml:39` sets `continue-on-error: true` on lint, and there is no `npm test`. Only `tsc -b` + build gate merges.
- **Backend CI gaps:** no coverage measurement and no `manage.py makemigrations --check --dry-run` (model/migration drift can merge undetected). `.github/workflows/backend-ci.yml`.

---

## 3. CRITICAL findings

### C1 — Live secrets present in `backend/.env` (rotate now)
`backend/.env` holds real, active credentials: M-Pesa consumer key/secret, an Africa's Talking API key (`atsk_…`), and a Gmail app password (`EMAIL_HOST_PASSWORD`). The file **is correctly git-ignored** (verified) so it is not in version control — but the values are live secrets sitting in plaintext on the dev machine and any host with read access can drain SMS credit or send mail as the business.
**Action:** rotate the AT key and Gmail app password; treat M-Pesa secrets as exposed. (`DEFAULT_FROM_EMAIL` also still reads the stale "Dr. Osoro Properties" brand.)

### C2 — M-Pesa C2B confirm trusts the client-supplied amount with no bound/reconciliation
`apps/payments/views_mpesa.py:172-189` records whatever `TransAmount` arrives and immediately recalculates tax + arrears from it. The **only** auth on the M-Pesa webhook is a hardcoded IP allowlist (`mpesa.py:47-49`), and `_get_client_ip` blindly trusts the first `X-Forwarded-For` entry (`views_mpesa.py:44-48`) — spoofable behind a proxy. The bank webhook is HMAC-protected; M-Pesa is not. A crafted request can inject an arbitrary payment and zero out a tenant's arrears.
**Action:** validate/bound webhook amounts; stop trusting raw XFF; document the trusted-proxy assumption.

### C3 — Payment double-processing: no DB uniqueness on `Payment.reference`
`apps/payments/models.py:64-80` — `reference` is indexed but **not unique**. All webhook handlers guard duplicates with a non-atomic `Payment.objects.filter(reference=…).exists()` check (`views_mpesa.py:128,164,270`; `bank.py:123`) *outside* any lock. Safaricom/banks retry on timeout; two concurrent retries both pass the check and both insert → **duplicate payment, doubled arrears reduction** under normal conditions.
**Action:** add a `UniqueConstraint`/`unique=True` on `reference` and catch `IntegrityError` in handlers.

---

## 4. HIGH findings

### H1 — Webhook tenant matching is cross-building ambiguous (wrong-tenant credit)
`views_mpesa.py:91-94` matches `Unit.objects.filter(label__iexact=house_number).first()`, but `Unit.label` is unique only **per building** (`apps/buildings/models.py:135`). Two buildings can both have unit "A1"; the payment is credited to whichever `.first()` returns. `bank.py:28` reuses the same matcher. → payments posted to the wrong tenant.

### H2 — STK Push is silently broken in every environment
`apps/payments/mpesa.py:131,151` read `settings.MPESA_PASSKEY` and `settings.MPESA_STK_CALLBACK_URL`, but **neither setting is defined** anywhere in `config/settings/*`. Every STK push (`views.py:165-185`) sends an empty passkey/callback → Daraja rejects or the callback never returns. The endpoint is non-functional.

### H3 — No object-level authorization anywhere (latent IDOR)
All viewsets use only `permission_classes = [IsAuthenticated]` (`payments/views.py:64`, `tenants/views.py:36`, etc.). There is no per-object ownership or role gate. Acceptable **today** because the system is single-admin — but nothing structurally prevents adding a second account, at which point it becomes a full IDOR over all financial and KYC data.

### H4 — KYC/identity documents may be served without authentication
Tenant documents (IDs, KRA certs) are stored via `FileField` under `MEDIA_ROOT` at a guessable path `tenant_docs/<tenant_id>/<filename>` (`apps/tenants/models.py:173-181`). There is no authenticated download view, and `original_name` is taken verbatim from the upload (`views.py:147`) with no sanitization (path-traversal risk). Depending on prod static config, PII may be retrievable by URL.

### H5 — Fetch errors are never surfaced; pages mislead or hang
No frontend page reads react-query's `isError` (0 hits across `src/pages`). A failed dashboard GET → **infinite loading skeleton** (`DashboardPage.tsx:89,97`); a failed tenants GET → the **"No tenants found" empty state** (`TenantsPage.tsx:537`), falsely telling the owner he has no tenants. No retry affordance exists on any data page.

---

## 5. MEDIUM findings

- **M1 — Arrears waivers silently reversed.** `_update_arrears` (`payments/services.py:100-126`) computes balance purely from `Payment.amount`, ignoring `Arrears.waived_amount`. A payment after a waiver overwrites it via `update_or_create` — `is_cleared` flips back, waiver lost. (`tenants/views.py:216-236`)
- **M2 — Float used for money in reporting/status paths.** `tenants/views.py:190-234`, `tenants/serializers.py:77,82`, and the statement running-balance use `float`, risking rounding drift. (Core `process_payment`/`tax_service` correctly use `Decimal`.)
- **M3 — Unmatched bank transfers are dropped entirely.** `bank.py:143-152` logs a warning and creates **no record** for funds it can't match — real money disappears from the system with only a log line.
- **M4 — File-upload validation trusts client `content_type`.** `tenants/services.py:29-39` checks browser-supplied MIME + size only; no magic-byte/extension/filename sanitization (stored-XSS / disguised-file risk, compounds H4).
- **M5 — Login lockout is per-email only (DoS + weak throttle).** `accounts/services.py:42-50` lets an attacker lock any known admin email for 30 min on demand, doesn't reset on success, and `LoginAttempt` grows unbounded.
- **M6 — STK endpoint leaks raw exception text** to clients (`payments/views.py:184-185`).
- **M7 — Tokens in `localStorage` (XSS theft).** `frontend/src/lib/authStorage.ts:8-9` stores access **and refresh** tokens in `localStorage`; any XSS yields a long-lived refresh token = silent session takeover. No CSRF handling exists, so the planned cookie migration will need it added.
- **M8 — Largest, most sensitive forms bypass zod.** Move-out / edit forms use bare `useForm()` (`TenantsPage.tsx:321-327`); deposit-refund % does `Number(v…)` with no guard → `NaN` into refund math. `MockPaymentPanel` amount is unvalidated free text (`PaymentsPage.tsx:218-224`).
- **M9 — `as unknown as` casts hide API-contract drift.** `TenantsPage.tsx:427,431-432,344` read `total_paid`/`total_arrears`/`care_of` that don't exist in `types.ts` → silent `KES 0` if the API changes.
- **M10 — Accessibility gaps vs the stated WCAG 2.1 AA target.** Modal has no focus trap or focus restoration (`Modal.tsx:50-58`) — a WCAG 2.4.3/2.1.2 failure on the app's primary interaction surface; shared `Field` labels lack `htmlFor`/`id`; filter tabs lack `aria-selected`; clickable table rows are mouse-only; `text-ink-400`/10–11px micro-text likely fails 4.5:1 contrast.
- **M11 — ErrorBoundary blanks the whole app and prints raw error text** to the user (`ErrorBoundary.tsx:42-44`); it sits outside the Router, so there's no per-route recovery and async/query errors never reach it.
- **M12 — CSP hardcodes `http://localhost:8000` in the production policy** (`accounts/middleware.py:24`); not parameterized by `FRONTEND_URL`.

---

## 6. LOW findings

- **L1** — `PasswordResetConfirmSerializer` is dead code (field name `password` vs view's `new_password`); validation duplicated inline (`accounts/views.py:111-164`).
- **L2** — Stale comments: "SendGrid" (`accounts/views.py:78`) though transport is Gmail SMTP.
- **L3** — `LoginAttempt` / `PasswordResetToken` have no pruning job (unbounded growth; used reset tokens never deleted).
- **L4** — Unauthenticated deep-link to a bad URL bounces to `/login`, not a 404 — the `path="*"` route sits inside `ProtectedRoute` (`App.tsx:43`).
- **L5** — `baseURL` falls back to `http://localhost:8000/api` if `VITE_API_BASE_URL` is unset (`api.ts:19`) — a misconfigured prod build calls localhost silently.
- **L6** — `authStorage.getUser()` `JSON.parse` has no try/catch (`authStorage.ts:28-30`); corrupt `wk_user` trips the ErrorBoundary on load.
- **L7** — Refresh request uses raw `axios.post`, bypassing the 10s timeout (`api.ts:44`).
- **L8** — Both `recharts` and `chart.js` are bundled; dashboard only uses recharts — likely dead weight.
- **L9** — Mutation errors usually show generic `toast.error("Failed")`, discarding the backend's `detail`.
- **L10** — `Tenant.email` not unique; `phone` has no model-level format validation.
- **L11** — ESLint uses only `recommended` (not type-checked), no `jsx-a11y` plugin — so the a11y/`any`/drift issues above are not caught by the lint gate.

---

## 7. What is done well

- **Production settings hardened:** `DEBUG=False` hardcoded, SSL redirect, HSTS (1yr + preload + subdomains), secure cookies, `nosniff`, `X-Frame-Options: DENY`, required `SECRET_KEY`/`ALLOWED_HOSTS`/`DATABASE_URL` (fail loud). (`config/settings/production.py`)
- **Bank webhook is fail-closed** on missing secret, uses timing-safe `hmac.compare_digest`, and has a regression test.
- **JWT config sound:** 15-min access tokens, refresh rotation + blacklist; password reset blacklists outstanding tokens. Client refresh uses correct single-flight de-duplication and avoids refresh loops.
- **Money core uses `Decimal` + `ROUND_HALF_UP`**, centralized in `tax_service.py`; `Transaction` immutably snapshots derived values; financial FKs use `on_delete=PROTECT`.
- **Password reset resists user enumeration**; 12-char min policy.
- **HTML email output consistently escaped** — no template injection.
- **Frontend foundations:** strict `tsconfig`, real loading/empty states on list pages, write-path errors caught with toasts, global `:focus-visible` ring + `prefers-reduced-motion`, vendor code-splitting, and an above-average Modal a11y base (just missing the focus trap).

---

## 8. Recommended remediation order (pre-Go-Live)

1. **C1** — Rotate exposed AT key + Gmail app password today.
2. **C3** — Unique constraint on `Payment.reference` + `IntegrityError` handling (closes the double-credit race) — **with a test**.
3. **H1** — Make webhook tenant matching building-aware (use the paybill prefix / full account, not bare `label`) — **with a test**.
4. **C2 / H4** — Bound & validate webhook amounts; stop trusting raw XFF; add an authenticated, sanitized document-download path.
5. **M1** — Fix arrears recalculation to respect `waived_amount` — **with a test**.
6. **H5 / M11** — Surface `isError` + retry on every data page; stop rendering empty/skeleton on failure.
7. **Test debt** — Add tests for `dashboard`/`expenses`/reports; stand up frontend vitest + RTL starting with payment/deposit/KYC logic; add `npm test` to frontend CI and remove `continue-on-error` from lint; add `makemigrations --check` to backend CI.

---

*Findings are evidence-based with file:line citations against the `feat/fixes` branch as of 2026-05-23. Citations from point-in-time memory should be re-verified before code changes.*
