# Go-Live Checklist

All application features (F1–F9) are built, merged, and on `main`. What remains is
infrastructure and the Co-op Bank cutover. Work through this in order — the phases
are sequenced because of two hard dependencies:

- **Redis must exist before any SMS can send.** The Celery worker and beat services
  cannot start without `REDIS_URL`, and every reminder, receipt, and alert is a
  Celery task.
- **The custom domain must be live before you contact Co-op.** Co-op allowlists the
  IPN endpoint **by domain**, and that domain can never change afterwards.

> **Deploy note.** Render deploys from the **fork** (`SharonKariuki/willkemedge-dashboard`),
> default branch `main` — not the `WILLKEMEDGE` org remote. Pushing to `origin/main`
> alone does **not** deploy. `backend/build.sh` runs `migrate --noinput` on every deploy.

---

## Phase 2 — Render infrastructure

### 2.1 Create the Redis instance

The blueprint cannot provision Redis, so it must be created by hand.

- [ ] Render → **New + → Redis**. Any paid plan; the free tier is not offered for Redis.
- [ ] Copy its internal connection URL into `REDIS_URL` on **all three** services
      (`wilkemedge-api`, `wilkemedge-celery`, `wilkemedge-beat`).

Until this is done the worker and beat services will crash-loop and **nothing that
sends an SMS or email will run at all.**

### 2.2 Fill the `sync: false` env vars

Render creates these keys from the blueprint but leaves them **empty** — it will not
invent values. Every one must be filled in the dashboard.

**`wilkemedge-api` (web)**

- [ ] `DJANGO_ALLOWED_HOSTS` — your API domain
- [ ] `DATABASE_URL` — the Neon Postgres URL
- [ ] `CORS_ALLOWED_ORIGINS` / `FRONTEND_URL` — the Vercel frontend URL
- [ ] `COOP_IPN_TOKEN` — generate a long random string; you will give this to Co-op
- [ ] `COOP_IPN_ALLOWED_IPS` — **leave blank for now**; fill in Phase 3 once Co-op
      confirms their source IPs. Blank means allow-all, which is why the bearer token
      matters in the meantime.
- [ ] `ADMIN_ALERT_PHONE` / `ADMIN_ALERT_EMAIL` — who hears about unmatched credits
- [ ] `DIRECTOR_ALERT_PHONE` / `DIRECTOR_ALERT_EMAIL` — Osoro, for reversal alerts
- [ ] `DIRECTOR_EMAIL` — Osoro's **login email**. This gates who may authorise a
      reversal in the Django admin. Distinct from `DIRECTOR_ALERT_EMAIL`. Left blank,
      the gate falls back to superuser-only.
- [ ] `AT_API_KEY` / `AT_USERNAME` / `AT_SENDER_ID` — Africa's Talking **live** creds
- [ ] `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` / `DEFAULT_FROM_EMAIL`
- [ ] `SENTRY_DSN`

**`wilkemedge-celery` (worker)** — this is the one that was silently misconfigured.
The tasks in `apps/payments/tasks.py` execute **here, not on web**, so these must be
set on the worker even though they look like duplicates of the web service:

- [ ] `DATABASE_URL`, `DJANGO_ALLOWED_HOSTS`
- [ ] `ADMIN_ALERT_PHONE` / `ADMIN_ALERT_EMAIL`
- [ ] `DIRECTOR_ALERT_PHONE` / `DIRECTOR_ALERT_EMAIL`
- [ ] `FRONTEND_URL` — password-reset emails are rendered here; without it the reset
      link in the email is broken
- [ ] `AT_API_KEY` / `AT_USERNAME` / `AT_SENDER_ID`
- [ ] `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` / `DEFAULT_FROM_EMAIL`
- [ ] `SENTRY_DSN`

**`wilkemedge-beat`**

- [ ] `DATABASE_URL`, `DJANGO_ALLOWED_HOSTS`, `SENTRY_DSN`

Already set from the blueprint, no action needed: `COOP_ACCOUNT_NUMBER`
(`01136069098300`), `MPESA_ACCOUNT_PREFIX` (`90290`), `COOP_IPN_TRUSTED_PROXY_COUNT`
(`1`, correct for Render's single proxy), `RENT_REMINDER_LEAD_DAYS` (`3`).

### 2.3 Domain and SSL

- [ ] Attach a **stable custom domain** to `wilkemedge-api` and let Render issue SSL.
- [ ] Add that domain to `DJANGO_ALLOWED_HOSTS`.

Do this **before** Phase 3. Co-op allowlists by domain, so it must be final.

### 2.4 Frontend

- [ ] Deploy the frontend to Vercel; set `VITE_API_BASE_URL` to the API domain.
- [ ] Point `CORS_ALLOWED_ORIGINS` and `FRONTEND_URL` at the Vercel URL.

### 2.5 Daily reconciliation scheduler

There is **deliberately no Render Cron service** — the HTTP trigger endpoint exists so a
free external scheduler can do this at no cost.

- [ ] Copy the generated `RECONCILIATION_TRIGGER_TOKEN` out of the `wilkemedge-api`
      dashboard (Render generates it; it is not shown anywhere else).
- [ ] Point a free scheduler (cron-job.org, GitHub Actions, UptimeRobot) at, daily:
      `POST https://<api-domain>/api/payments/coop/reconcile-daily/?token=<TOKEN>`
      Bearer header also works: `Authorization: Bearer <TOKEN>`.

### 2.6 Verify the infrastructure is actually alive

- [ ] `GET https://<api-domain>/api/health/` returns 200.
- [ ] `wilkemedge-celery` and `wilkemedge-beat` logs show a clean start, no Redis errors.
- [ ] Trigger a Sentry test event and confirm it lands in the Sentry project.
- [ ] Send yourself a password reset and confirm **the link in the email works** — this
      exercises the worker, `FRONTEND_URL`, and email creds in one shot.

Beat schedule, for reference (timezone `Africa/Nairobi`, so these are EAT):

| Time | Task |
|---|---|
| 00:05, 1st of month | `generate_monthly_arrears` |
| 00:30 daily | `recalculate_all_statuses` |
| 08:00 daily | `send_rent_reminders` |
| 09:00 daily | `send_arrears_reminders` |
| hourly | `poll_bank_statement` (Co-op backfill stub — inert until configured) |

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
