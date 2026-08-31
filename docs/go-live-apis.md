# Go-Live: External APIs & Integrations — Step by Step

Everything you need to sign up for and wire so the deployed system is fully
functional. Companion to [go-live-checklist.md](go-live-checklist.md) (which
covers the deployment/env plumbing) and [coop-ipn-security.md](coop-ipn-security.md).

**There is no M-Pesa Daraja integration.** Payment collection is 100% via the
**Co-op Bank IPN** — Co-op forwards every M-Pesa credit to Paybill **400222** to
our webhook. So the only "M-Pesa" setup is the Co-op IPN below.

## Where each value goes

| Layer | Where | Which vars |
|---|---|---|
| Backend | **Render** → `willkemedge-dashboard` → Environment | everything except `VITE_*` |
| Frontend | **Vercel** → Project → Settings → Environment Variables | `VITE_*` only |

After changing Render env vars, the service restarts automatically. After
changing Vercel vars you must **redeploy** the frontend.

Generate any secret token with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

---

## 1. Africa's Talking — SMS

Powers rent/arrears reminders, SMS receipts, and admin/director alerts.

1. Create/log in at <https://africastalking.com> and create an **App** (production, not sandbox).
2. Top up an SMS balance (KES) and, if you want a branded sender, apply for an **Alphanumeric Sender ID** (e.g. `WILKEM`) — this takes network approval, so start it early.
3. Copy the **API key** (Settings → API Key) and note your **username** (the app name).
4. Set on **Render**:
   - `AT_API_KEY` = the API key
   - `AT_USERNAME` = your live app username (change it away from `sandbox`)
   - `AT_SENDER_ID` = your approved sender ID (leave blank until approved)
5. **Test** from the Render shell:
   ```bash
   python manage.py shell -c "from apps.payments.notifications import send_sms; print(send_sms('+2547XXXXXXXX', 'Wilkem test'))"
   ```
   A non-`None` response = sent. (With no key it logs "SMS skipped" and returns `None`.)

> SMS only sends when a key is set **and** the scheduled jobs fire — see §4.

---

## 2. Gmail SMTP — Email

Powers email statements/receipts and password-reset emails. Sends from
`wilkem.ventures@gmail.com`.

1. On that Google account, enable **2-Step Verification** (required for app passwords).
2. Google Account → **Security → App passwords** → create one for "Mail". Copy the **16-character** code.
3. Set on **Render**:
   - `EMAIL_HOST_PASSWORD` = the 16-char code (**no spaces**)
   - (already defaulted, confirm: `EMAIL_HOST=smtp.gmail.com`, `EMAIL_PORT=587`, `EMAIL_USE_TLS=True`, `EMAIL_HOST_USER=wilkem.ventures@gmail.com`, `DEFAULT_FROM_EMAIL`)
4. **Test** from the Render shell:
   ```bash
   python manage.py shell -c "from django.core.mail import send_mail; send_mail('Wilkem test','It works.','wilkem.ventures@gmail.com',['you@example.com'])"
   ```

---

## 3. Co-op Bank IPN — payment collection (the "M-Pesa" path)

This is how paid rent reaches the system. Do the **production domain first**
(§2.2 of the checklist) — Co-op allowlists the endpoint **by domain** and it
cannot change afterwards.

1. **Generate the shared token** and set it on **Render**:
   - `COOP_IPN_TOKEN` = a fresh `secrets.token_urlsafe(48)` value.
2. Confirm the account guard (already defaulted): `COOP_ACCOUNT_NUMBER=01136069098300`, `COOP_IPN_TRUSTED_PROXY_COUNT=1` (Render edge).
3. **Give Co-op**: the IPN URL `https://<your-api-domain>/api/payments/coop/ipn/` and the `COOP_IPN_TOKEN` (they present it as a Bearer token on each POST).
4. Ask Co-op to run their **Postman/UAT test** against the endpoint. Capture the source IP(s) they call from (also visible in the stored `CoopIpnEvent.raw_payload` / Render logs).
5. Set the allowlist on **Render**:
   - `COOP_IPN_ALLOWED_IPS` = Co-op's confirmed IP/CIDR (comma-separated). Requests from other IPs get **403** before the token is even checked.
6. **Verify** with a real M-Pesa payment to Paybill 400222 → it should appear under Payments (or Reconciliation if the narration can't be matched to a unit).

Full detail + spoofing defence: [coop-ipn-security.md](coop-ipn-security.md).

---

## 4. Scheduled jobs — free external cron (REQUIRED for reminders)

There is **no Celery beat**. Reminders/statements only run when an external
scheduler calls the token-gated endpoints. Without this, the AT key alone sends
nothing on a schedule.

1. **Generate the trigger token** and set on **Render**:
   - `CRON_TRIGGER_TOKEN` = a fresh `secrets.token_urlsafe(48)` value.
2. Pick a free scheduler — **cron-job.org**, **UptimeRobot**, or a **GitHub Actions** scheduled workflow.
3. Add one job per task below. Method GET or POST; auth via header `Authorization: Bearer <CRON_TRIGGER_TOKEN>` (or `?token=<token>` in the URL).

   `https://<your-api-domain>/api/payments/cron/<job>/`

   | `<job>` slug | What it does | Suggested schedule (EAT) |
   |---|---|---|
   | `rent-reminders` | SMS N days before each tenant's due day | daily 08:00 |
   | `arrears-reminders` | SMS on/after due day when unpaid | daily 09:00 |
   | `monthly-arrears` | Raise **next** month's rent | 25th of month 06:30 |
   | `monthly-statements` | Email every tenant **next** month's statement PDF | 25th of month 07:00 |
   | `monthly-arrears` | Catch up any month the 25th missed | 1st of month 00:30 |
   | `recalculate-statuses` | Refresh unit paid/unpaid/arrears status | daily 01:00 |
   | `daily-reconciliation` | Email the unmatched-credit summary | daily 18:00 |

   The two monthly jobs run a month ahead of the calendar, which tenants asked
   for: on 25 August they raise and email **September**, so the bill arrives
   before the month it covers rather than after it has begun. The day is
   `STATEMENT_RUN_DAY` in Django settings (default 25) — move it and you must
   move the scheduler's cron lines to match, or the jobs fire on a day that
   bills the month already in progress.

   `monthly-statements` runs half an hour *after* `monthly-arrears`, which is
   what raises the rent — a statement sent before it states a balance with the
   stated month missing. It takes an optional `?period=YYYY-MM` to re-issue a
   month, only writes to tenants who have an email address on file, and sends
   each tenant at most one statement per month, so it is safe to re-run.

   A period raised on the 25th is charged, not overdue: the rent roll, the aging
   table, the unit-status sweep and the reminder SMS balances all stop at the
   current calendar month, so nobody is reported a month in arrears for the last
   week of a month.

   **`TENANT_NOTIFICATIONS_ENABLED=false` silences this job** along with receipts
   and reminders — the run records each statement as PENDING and sends nothing.
   Check that setting on Render before relying on the schedule. Sending from the
   dashboard by hand is deliberately *not* silenced: a person chose it and is
   watching the result.

4. **Test** one:
   ```bash
   curl -H "Authorization: Bearer <CRON_TRIGGER_TOKEN>" https://<your-api-domain>/api/payments/cron/rent-reminders/
   ```
   `401` = bad/missing token; `404` = wrong slug; `200` with a result = success.

---

## 5. Sentry — error monitoring (recommended)

1. Create a project at <https://sentry.io> → Settings → **Client Keys (DSN)**.
2. **Backend** — set on **Render**: `SENTRY_DSN`, `SENTRY_ENVIRONMENT=production`. (It's a no-op until the DSN is set.)
3. **Frontend** — set on **Vercel**: `VITE_SENTRY_DSN`, `VITE_SENTRY_ENVIRONMENT=production`, then **redeploy** the frontend.

---

## 6. Alert recipients (plain config, not APIs)

Set on **Render** so unmatched-credit / error alerts reach a human, and so
reversals can be authorised:

- `ADMIN_ALERT_PHONE`, `ADMIN_ALERT_EMAIL`
- `DIRECTOR_ALERT_PHONE`, `DIRECTOR_ALERT_EMAIL`
- `DIRECTOR_EMAIL` — the director's **login** email; only this user may authorise a payment reversal.

---

## Final verification

- [ ] SMS test (§1) returns a response
- [ ] Email test (§2) arrives
- [ ] Co-op UAT payment appears in the app (§3)
- [ ] `COOP_IPN_ALLOWED_IPS` set → non-allowlisted callers get 403
- [ ] Each cron slug returns 200 with the token (§4); scheduler jobs created
- [ ] Sentry receives a test event both ends (§5)
- [ ] Alert recipients + `DIRECTOR_EMAIL` set (§6)

Priority for a working system: **§3 Co-op IPN** (money in) → **§1 AT + §4 cron**
(SMS/reminders) → **§2 email** → **§5 Sentry**.
