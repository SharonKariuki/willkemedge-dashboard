# Co-op Bank IPN — Webhook Security Runbook

Endpoint: `POST /api/payments/coop/ipn/` (`apps/payments/coop_ipn.py`)

Co-op posts an Instant Payment Notification for every credit on the institution
account behind **Paybill 400222** (M-Pesa collections + direct bank deposits).
This document covers the access controls and the Day 2 go-live steps.

## Layered access controls (in order)

1. **Source-IP allowlist** — first gate. A request whose client IP is **not** in
   `COOP_IPN_ALLOWED_IPS` is rejected with **403 Forbidden**, before the token
   is examined. Empty list = allow all (the pre-go-live default, until Co-op
   shares their range).
   - Entries may be single IPs (`196.201.214.200`) or CIDR ranges
     (`196.201.214.0/24`). A bank usually posts from a subnet.
   - The client IP is resolved spoof-resistantly: it is read from the
     **trusted-proxy position** in `X-Forwarded-For`, not the leftmost
     (client-supplied) entry. `COOP_IPN_TRUSTED_PROXY_COUNT` controls how many
     proxies sit in front of the app (Render edge = `1`).
2. **Bearer token** — `Authorization: Bearer <COOP_IPN_TOKEN>`, timing-safe,
   fail-closed. Missing/invalid → **401 Unauthorized**.
3. **Per-IP throttle** (`coop_ipn` scope) so retry storms/brute force can't
   overwhelm the endpoint.
4. Account guard, strict-CREDIT, atomic idempotency — see the module docstring.

## Configuration

| Env var | Purpose | Example |
|---|---|---|
| `COOP_IPN_ALLOWED_IPS` | Comma-separated source IPs/CIDRs. Empty = allow all. | `196.201.214.0/24,196.201.213.44` |
| `COOP_IPN_TRUSTED_PROXY_COUNT` | Proxies in front of the app (Render = 1; 0 = none). | `1` |
| `COOP_IPN_TOKEN` | Shared secret Co-op presents. Generate with `python -c "import secrets; print(secrets.token_urlsafe(48))"`. | _(secret)_ |
| `COOP_ACCOUNT_NUMBER` | Institution account behind Paybill 400222. | `01136069098300` |

On Render these are set on the web service; `COOP_IPN_TOKEN` and
`COOP_IPN_ALLOWED_IPS` are `sync: false` (set by hand, never committed).

## Co-op source IPs — ALLOWLIST (fill in at go-live)

> **ACTION (ops):** Co-op must confirm the egress IP/CIDR their IPN gateway
> posts from. Until then `COOP_IPN_ALLOWED_IPS` is left **blank** (allow all),
> and the bearer token + throttle are the active controls. Record the confirmed
> values here and in the Render env var:

```
# Confirmed by Co-op on <date>, contact <name/email>:
# COOP_IPN_ALLOWED_IPS=<ip-or-cidr>,<ip-or-cidr>
```

## Postman test (Day 2 acceptance)

1. With the allowlist still blank (or your test machine's IP added), set
   `COOP_IPN_TOKEN` and have Co-op fire their Postman test against the
   production URL.
2. Expect `200 {"MessageCode":"200","Message":"Successfully received data"}`.
3. Confirm a `CoopIpnEvent` row was written (Django admin → Coop IPN events).
4. Negative check: replay from a non-allowlisted IP once `COOP_IPN_ALLOWED_IPS`
   is set → expect **403**.

## Capturing the real M-Pesa narration sample (for Day 3 parser)

Every delivery stores the **full raw payload** on the `CoopIpnEvent` row
(`raw_payload`) plus the `narration` string — no extra capture step is needed.
After the Postman/live test, retrieve the real narration layout:

```bash
python manage.py shell -c "from apps.payments.models import CoopIpnEvent; \
e=CoopIpnEvent.objects.latest('received_at'); print(e.narration); print(e.raw_payload)"
```

Store the confirmed narration layout against the Day 3 parser
(`_parse_narration`) so the bill-ref position (e.g. `RB001`) is pinned to real
data rather than the spec sample.

## Coordination (per sprint plan)

- **Barclay:** finalise the unit-label format (`RB001`) before the Day 3
  narration parser relies on it.
- Day 2 depends on Day 1 infra go-live being merged.
