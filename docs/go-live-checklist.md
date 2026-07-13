# Go-Live Checklist

All application features (F1–F9) are built, merged, and on `main`. What remains is
configuration and the Co-op Bank cutover.

## The deployment, as it actually is

Production is **one hand-created Render web service, `willkemedge-dashboard`** (Starter
plan). There is no Redis, no Celery worker, and no beat process, and there will not be
— each would be another paid instance, which is hard to justify at this scale. Instead:

- **Async tasks run inline in the web request.** `production.py` sets
  `CELERY_TASK_ALWAYS_EAGER=True`, so receipts, SMS, and alerts still send with no
  broker and no worker.
- **Scheduled jobs are driven by a free external scheduler** (cron-job.org, GitHub
  Actions) calling the token-gated endpoints at `/api/payments/cron/<job>/`.

> **`render.yaml` does not configure the live service.** It has never been applied, and
> its service names don't match, so applying it would create a *duplicate* web service.
> Env vars must be set **by hand** in the `willkemedge-dashboard` dashboard.

> **Deploy note.** Render deploys from the **fork**
> (`SharonKariuki/willkemedge-dashboard`), default branch `main` — not the `WILLKEMEDGE`
> org remote. Pushing to `origin/main` alone does **not** deploy. `backend/build.sh`
> runs `migrate --noinput` on every deploy.

**Do the domain (2.2) before Co-op (Phase 3)** — Co-op allowlists the IPN endpoint *by
domain*, and it can never change afterwards.

---

## Phase 2 — Configure the live service

### 2.1 Set the env vars on `willkemedge-dashboard`

Nothing sets these for you. In the Render dashboard → Environment:

- [ ] `DJANGO_ALLOWED_HOSTS` — your API domain
- [ ] `DATABASE_URL` — the Neon Postgres URL
- [ ] `CORS_ALLOWED_ORIGINS` / `FRONTEND_URL` — the Vercel frontend URL.
      `FRONTEND_URL` is also what builds the link in password-reset emails.
- [ ] `CRON_TRIGGER_TOKEN` — generate with
      `python -c "import secrets; print(secrets.token_urlsafe(48))"`. This is the
      secret the scheduler presents in 2.3.
- [ ] `COOP_IPN_TOKEN` — a second, *different* random string. You give this one to Co-op.
- [ ] `COOP_IPN_ALLOWED_IPS` — **leave blank for now**; filled in Phase 3 once Co-op
      confirms their source IPs. Blank means allow-all, which is why the bearer token
      carries the weight in the meantime.
- [ ] `COOP_ACCOUNT_NUMBER` = `01136069098300`
- [ ] `COOP_IPN_TRUSTED_PROXY_COUNT` = `1` (correct for Render's single edge proxy)
- [ ] `MPESA_ACCOUNT_PREFIX` = `90290`
- [ ] `ADMIN_ALERT_PHONE` / `ADMIN_ALERT_EMAIL` — who hears about unmatched credits
- [ ] `DIRECTOR_ALERT_PHONE` / `DIRECTOR_ALERT_EMAIL` — Osoro, for reversal alerts
- [ ] `DIRECTOR_EMAIL` — Osoro's **login email**. Gates who may authorise a reversal in
      the Django admin. Distinct from `DIRECTOR_ALERT_EMAIL`; blank falls back to
      superuser-only.
- [ ] `AT_API_KEY` / `AT_USERNAME` / `AT_SENDER_ID` — Africa's Talking **live** creds
- [ ] `RENT_REMINDER_LEAD_DAYS` = `3`
- [ ] `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` / `DEFAULT_FROM_EMAIL`
- [ ] `SENTRY_DSN` (+ `SENTRY_ENVIRONMENT=production`)

### 2.2 Domain and SSL

- [ ] Attach a **stable custom domain** and let Render issue SSL.
- [ ] Add that domain to `DJANGO_ALLOWED_HOSTS`.

### 2.3 Point a free scheduler at the cron endpoints

This replaces Celery beat. Sign up at cron-job.org (free) and create one job per row.
Each is a `POST`, with the token either as `?token=<CRON_TRIGGER_TOKEN>` or an
`Authorization: Bearer <CRON_TRIGGER_TOKEN>` header. Times are **EAT**, matching the
original beat schedule.

| Schedule | URL |
|---|---|
| 00:05, 1st of month | `POST /api/payments/cron/monthly-arrears/` |
| 00:30 daily | `POST /api/payments/cron/recalculate-statuses/` |
| 08:00 daily | `POST /api/payments/cron/rent-reminders/` |
| 09:00 daily | `POST /api/payments/cron/arrears-reminders/` |
| 03:00 daily | `POST /api/payments/cron/daily-reconciliation/` |

- [ ] All five jobs created and returning **200**.

**`monthly-arrears` is the one that matters most.** It is the only thing that creates an
`Arrears` row for a tenant who has *not* paid — tenants who do pay get their rows created
lazily when the payment is processed. Without it, defaulters produce no arrears record at
all: no arrears reminder, no "in arrears" unit status, and nothing on the arrears report.
The people the dashboard exists to surface are exactly the ones who go missing.

A failed run returns 500, so the scheduler's history shows red rather than failing quietly.

### 2.4 Backfill the arrears that were never generated

Beat has never run in production, so `generate_monthly_arrears` has never fired for any
month since the June property load.

- [ ] In Django admin, check whether `Arrears` rows exist for the current month.
- [ ] If not, fire `POST /api/payments/cron/monthly-arrears/` once by hand. It is
      idempotent (`get_or_create`), so it is safe to run repeatedly.
- [ ] Then fire `recalculate-statuses` so unit statuses catch up.

### 2.5 Frontend

- [ ] Deploy the frontend to Vercel; set `VITE_API_BASE_URL` to the API domain.
- [ ] Point `CORS_ALLOWED_ORIGINS` and `FRONTEND_URL` at the Vercel URL.

### 2.6 Verify it is actually alive

- [ ] `GET https://<api-domain>/api/health/` returns 200.
- [ ] A cron endpoint called **without** a token returns 401 (it must fail closed).
- [ ] Trigger a Sentry test event and confirm it lands in the Sentry project.
- [ ] Send yourself a password reset and confirm **the link in the email works** — one
      action that exercises inline task execution, `FRONTEND_URL`, and the email creds.

---

## Phase 3 — Co-op Bank IPN cutover

This is what makes payments actually flow in, and it is the longest pole because it
depends on Co-op's turnaround.

Contact: **the Co-op contact**, Digital Integrations & Ecommerce — `[redacted]`.
Technical contact on the signed B2B form: `[redacted]`.
Paybill **400222** (Co-op-aggregated), account format `90290#<UNIT_CODE>`.

- [ ] Send Melvin the live endpoint and the bearer token you set as `COOP_IPN_TOKEN`:
      `https://<api-domain>/api/payments/coop/ipn/`
- [ ] Ask him to run the **Postman simulation** against it. There is no sandbox — Co-op
      simulates POSTs to the live endpoint.
- [ ] **Capture the two unknowns this resolves.** Every payload is persisted verbatim to
      `CoopIpnEvent.raw_payload`, so no extra capture code is needed — just read the rows
      back in Django admin:
  - [ ] The **real M-Pesa narration format** — confirm where the tenant's bill-ref
        actually sits in the string. Tune `_parse_narration` in
        `apps/payments/coop_ipn.py` if it is not where the parser expects.
  - [ ] Co-op's **source IPs** → set `COOP_IPN_ALLOWED_IPS` (CIDR supported).
- [ ] Run **one real end-to-end payment**: pay Paybill 400222 with a real unit code,
      then confirm the payment booked to the right tenant, arrears updated, and the
      receipt SMS arrived.
- [ ] Confirm an **unmatched** credit raises the admin alert (this is the path that was
      dead before the `render.yaml` fix — worth proving it works).

See `docs/coop-ipn-security.md` for the IP-allowlist and proxy-header details.

---

## Phase 4 — Load Matasia

The `import_matasia` command is built and dry-run clean (36 units, 24 commercial +
12 residential, 14 occupied, base rent 701,455, opening 480,642) but has **never been
run against a real database.**

**Two questions must be answered by Dr. Osoro before loading real money:**

- [ ] **MCG02** shows **0 VAT** on the rent-roll sheet, but will receive 16% VAT under
      the BUSINESS classification — the model applies VAT by classification, not per
      unit. Is MCG02 genuinely VAT-exempt, or is the sheet wrong? (The command warns.)
- [ ] Business names containing `" - "` (e.g. `Glow - by - Ellie - Salon`) get split
      into first/last name by `load_property_data`. Accept, or clean the source first?

Then:

- [ ] Run `import_matasia --dry-run` on Render and check the totals still tie.
- [ ] Load for real. Use a **Render Secret File** for the source data — the web shell
      cannot accept large multi-line pastes (this is how the June property load was done).
- [ ] The source `.xlsx` contains real tenant PII and must **not** be committed.

---

## Phase 5 — Close out

- [ ] Close stale PRs: **#63** (superseded — the same branch already merged as #64) and
      **#20** (open since 18 June).
- [ ] Decide on the one genuinely unbuilt feature: applying an **authorised reversal** is
      still manual via Django admin. The one-click authorise → reverse workflow was
      deferred. Reversals correctly alert Osoro and never auto-undo a payment, so this is
      a convenience gap, not a correctness one.
