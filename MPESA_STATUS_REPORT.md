# M-Pesa Integration — Status Report

**Prepared for:** Dr. William Osoro
**Prepared by:** Sharon, Wilkem Ventures rental management system
**Date:** 17 May 2026
**Status:** Blocked — awaiting Co-op Bank API access

---

## Executive summary

The rental management dashboard is functionally complete: tenants, units, payments, arrears, reporting, SMS notifications and email statements all work. The final piece — **automatically pulling M-Pesa payments from Paybill 400222 into the system** — is blocked on Co-operative Bank, who own the technical pipe between Safaricom and Wilkem's bank account.

We can proceed once Co-op grants us API access. The blocker is administrative, not technical. **We need you to authorise the request and provide three business documents.**

---

## What's been built and is working

| Capability | Status |
|---|---|
| Buildings, units, occupancy tracking | Complete |
| Tenant management, KYC, lease lifecycle | Complete |
| Manual payment recording and receipt | Complete |
| Arrears tracking and recalculation | Complete |
| SMS receipts (Africa's Talking) | Complete |
| Email receipts with PDF rent statements | Complete |
| Reporting and dashboard | Complete |
| M-Pesa webhook receivers (code) | Complete — waiting on credentials |
| Production deployment configuration | Ready — pending hosting account setup |

Once M-Pesa is connected, the loop closes: a tenant pays Paybill 400222, the dashboard records it within minutes, the tenant gets an SMS receipt and an email with their updated statement automatically.

---

## What is blocked, and why

**Paybill 400222 is issued by Co-operative Bank.** Safaricom routes payments to it via Co-op's banking system, so the technical pipe to receive automated payment notifications goes through **Co-op**, not Safaricom directly. This is standard for bank-aggregated Paybills.

After researching Co-op's developer portal and their published API:
- Co-op offers two relevant integration paths
- Both require Co-op to manually onboard Wilkem Ventures as an API customer
- Self-registration on their developer portal is currently broken (returns "Unexpected Error")

**Path A — Real-time notifications (preferred):** Co-op's "B2B Instant Notification Service" pushes a notification to the dashboard the moment a tenant pays Paybill 400222. Tenants receive their SMS receipt within seconds. This requires direct enrollment via Co-op's B2B/Cash Management team.

**Path B — Polling (fallback):** If Path A is unavailable, we use Co-op's published "Account Transactions" API to check the Paybill account every few minutes and reconcile new payments. Receipts arrive 1–5 minutes after payment instead of seconds. Self-serve credentials, simpler onboarding.

We do not know yet which path will be approved for Wilkem Ventures — that is determined by Co-op based on the integration request.

---

## Decision required from Dr. Osoro

**Option 1 — Direct integration with Co-op Bank (recommended)**
- Cost: nothing per transaction
- Timeline: 1–3 weeks (depends on Co-op's onboarding speed)
- Risk: Co-op's process pace is outside our control

**Option 2 — Use a payment aggregator (Pesapal, IntaSend, or Flutterwave)**
- Cost: ~1.5–2.5% fee on every rent payment received
- Timeline: 3–5 working days to live integration
- Money still settles to your Co-op Paybill, but reconciliation goes through the aggregator's webhook API

For context: at typical monthly collections of (e.g.) KES 500,000, a 1.5% aggregator fee would cost ~KES 7,500/month or KES 90,000/year. Direct Co-op integration is free per transaction but takes longer to enable.

**Please advise which option to pursue.** If Co-op direct, we proceed below. If aggregator, the document checklist below becomes lighter and the integration finishes faster.

---

## What we need from you to proceed (Co-op direct path)

1. **Authorisation to contact Co-op on Wilkem Ventures' behalf** — a brief WhatsApp or email confirmation is enough. Co-op will likely want to verify with you directly before granting access.

2. **Wilkem Ventures KRA PIN** — required for Co-op's KYC verification. Format is P followed by 9 digits and a letter (e.g. P051234567A).

3. **Certificate of Incorporation (scan)** — Wilkem Ventures Company Limited registration document. PDF or clear photo is fine.

4. **Director's National ID (scan)** — your ID, front and back.

5. **Your email address** — to be CC'd on the Co-op onboarding email so they see the request is authorised by you.

6. **Any existing Co-op Relationship Manager** — if Wilkem Ventures has a dedicated banker at Co-op, please share their name and contact. Going through an RM typically halves the onboarding time.

---

## What we need from you to proceed (aggregator path)

If you prefer the aggregator route, we need only:

1. **Authorisation to register Wilkem Ventures with an aggregator (Pesapal, IntaSend, or Flutterwave)** — your choice; I can prepare a one-page comparison if needed.
2. **Wilkem Ventures KRA PIN and Certificate of Incorporation** — aggregators KYC the business too.
3. **Director's National ID (scan)** — for the merchant account.

The aggregator handles the Co-op + Safaricom complexity behind the scenes. Money still arrives in your Co-op Paybill account; only the technical notification path changes.

---

## Timeline

**Assuming Co-op direct path:**

| Step | Lead time | Owner |
|---|---|---|
| You provide documents above | 1 day | Dr. Osoro |
| Email sent to Co-op | Same day | Sharon |
| Co-op responds with API docs + sandbox credentials | 2–5 business days | Co-op |
| Adapt code to Co-op's payload, integration test | 1 day | Sharon |
| Submit production Go-Live request to Co-op | Same day | Sharon |
| Co-op approves production credentials | 1–5 business days | Co-op |
| Production cutover and live test (KES 10) | 1 hour | Sharon + Dr. Osoro |

**Total: 1–3 weeks from the day documents are received**, dependent on Co-op's pace.

**Assuming aggregator path:** roughly 3–5 working days end-to-end.

---

## Costs

| Item | Cost |
|---|---|
| Africa's Talking SMS credits | ~KES 0.80 per SMS (already in test) |
| Backend hosting (Render or equivalent) | Free tier sufficient; paid tier ~USD 7/month if needed |
| Co-op direct integration | No per-transaction fee |
| Aggregator integration | ~1.5–2.5% per M-Pesa rent payment received |

---

## Recommended next step

Please confirm:
1. Which path (Co-op direct or aggregator)
2. When you can send the three documents (KRA PIN, Certificate of Incorporation, your National ID)
3. Whether Wilkem Ventures has an existing Co-op Bank Relationship Manager

Once received, the email to Co-op goes out the same day, and we begin the timeline above.
