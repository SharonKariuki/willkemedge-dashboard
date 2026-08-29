"""
Notification helpers — SMS via Africa's Talking, email via SMTP.

All functions are thin wrappers. They raise on failure so the calling
Celery task can retry with exponential backoff.

Required settings (all optional in dev — if absent, notifications are
logged only):
    AT_API_KEY, AT_USERNAME, AT_SENDER_ID
    EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, DEFAULT_FROM_EMAIL
"""
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils.html import escape

logger = logging.getLogger(__name__)


def _e(value) -> str:
    """HTML-escape any value before interpolating into f-string email HTML."""
    return escape("" if value is None else str(value))


# ---------------------------------------------------------------------------
# SMS — Africa's Talking
# ---------------------------------------------------------------------------

def to_intl_phone(phone: str) -> str:
    """Normalise a Kenyan phone number to +254… international format for AT.

    Africa's Talking requires E.164 (`+2547XXXXXXXX`). Tenants loaded from the
    rent roll are already normalised, but a number typed into the UI may arrive
    as `07XXXXXXXX`, a bare `7XXXXXXXX`, or `2547XXXXXXXX` — coerce them all so
    a live send doesn't silently fail on format. Non-Kenyan numbers already in
    `+CC…` form are passed through unchanged.
    """
    raw = str(phone or "").strip()
    if raw.startswith("+"):
        return "+" + "".join(c for c in raw[1:] if c.isdigit())
    digits = "".join(c for c in raw if c.isdigit())
    if not digits:
        return ""
    if digits.startswith("0"):
        digits = "254" + digits[1:]
    elif digits.startswith("254"):
        pass
    elif digits.startswith(("7", "1")) and len(digits) == 9:
        # Bare local subscriber number (Safaricom/Airtel 7…, newer 1… ranges).
        digits = "254" + digits
    return "+" + digits


# Africa's Talking statusCodes that mean the message was accepted for delivery
# (Processed / Sent / Queued). Everything else is a per-recipient rejection.
_AT_ACCEPTED_STATUS_CODES = {100, 101, 102}

# Map AT rejection statuses to plain-language reasons a non-technical operator
# can act on. Unlisted statuses fall back to the raw AT status text.
_AT_FAILURE_REASONS = {
    "UserInBlacklist": "Recipient has blocked promotional SMS (they must dial *456*9# to opt back in)",
    "InvalidPhoneNumber": "Phone number is not valid",
    "UnsupportedNumberType": "This number cannot receive SMS",
    "InsufficientBalance": "SMS account balance is too low",
    "InvalidSenderId": "Sender ID is not registered/approved",
    "RiskHold": "Message held by Africa's Talking risk review",
    "CouldNotRoute": "Carrier could not route the message",
    "UserDoesNotExist": "Number is not a valid subscriber",
    "UserInInvalidState": "Recipient number cannot currently receive messages",
}


def at_delivery_error(receipt: dict | None) -> str | None:
    """Return a plain-language reason if an AT send receipt reports a per-recipient
    failure, else ``None``.

    Africa's Talking answers the send call with HTTP 200 even when the carrier
    rejects the recipient (e.g. ``UserInBlacklist``) — the true outcome lives in
    the per-recipient ``status``/``statusCode``. ``send_sms`` therefore cannot
    raise on these; callers must inspect the receipt to know whether delivery
    was actually accepted, otherwise a blocked message looks like a success.
    """
    if not receipt:
        return None
    data = receipt.get("SMSMessageData") if isinstance(receipt, dict) else None
    if not isinstance(data, dict):
        return None
    recipients = data.get("Recipients") or []
    if not recipients:
        # Nobody was accepted — surface the batch-level message if AT gave one.
        batch_msg = str(data.get("Message", "")).strip()
        return f"Not delivered: {batch_msg}" if batch_msg else "Not delivered"
    recipient = recipients[0]
    code = recipient.get("statusCode")
    status = str(recipient.get("status", "")).strip()
    if code in _AT_ACCEPTED_STATUS_CODES or status in ("Success", "Sent"):
        return None
    return _AT_FAILURE_REASONS.get(status, f"Not delivered ({status or code or 'unknown'})")


def send_sms(phone: str, message: str) -> dict | None:
    """
    Send an SMS via Africa's Talking REST API (using httpx).

    We call the API directly instead of the `africastalking` SDK because
    the SDK's `requests` dependency hits an SSL error on Windows with
    urllib3 2.x.  httpx works reliably.

    The phone is normalised to +254… international format before sending;
    when AT_SENDER_ID is configured (an approved alphanumeric sender ID or
    short code) it is passed as the `from` field so tenants see the branded
    sender instead of a shared masked number.

    Returns the parsed Africa's Talking response (the delivery receipt — it
    carries the per-recipient status, cost, and messageId) on success, or
    None when sending is skipped because no API key is configured. Raises on
    a real send failure so the caller can record it.
    """
    import httpx

    api_key = getattr(settings, "AT_API_KEY", "")
    username = getattr(settings, "AT_USERNAME", "sandbox")
    sender_id = getattr(settings, "AT_SENDER_ID", "")

    if not api_key:
        # Never log the recipient or the body: SMS content carries tenant names,
        # balances and payment references (Data Protection Act 2019). The IPN
        # path already masks phone numbers; this one used to log both in full.
        logger.warning("SMS skipped (AT_API_KEY not set): %d-char message suppressed", len(message or ""))
        return None

    to = to_intl_phone(phone)
    env = "sandbox" if username == "sandbox" else "live"
    base = f"https://api.{env}.africastalking.com" if env == "sandbox" else "https://api.africastalking.com"

    payload = {"username": username, "to": to, "message": message}
    if sender_id:
        payload["from"] = sender_id

    try:
        resp = httpx.post(
            f"{base}/version1/messaging",
            headers={
                "apiKey": api_key,
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data=payload,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        logger.info("SMS sent to %s: %s", to, data)
        return data
    except Exception as exc:
        logger.error("SMS failed to %s: %s", to, exc)
        raise


# ---------------------------------------------------------------------------
# Email — SMTP (Gmail in dev/MVP, swap host for any other SMTP provider)
# ---------------------------------------------------------------------------

def send_email(
    to_email: str,
    subject: str,
    html_content: str,
    text_content: str = "",
    attachments: list[tuple[str, bytes, str]] | None = None,
) -> bool:
    """
    Send a transactional email via SMTP (Django's built-in mail backend).

    attachments : optional list of (filename, content_bytes, mimetype) tuples.

    Returns True when the message was handed to the mail backend, False when no
    SMTP credentials are configured and the send was skipped. Callers that record
    the outcome need to tell those apart — without it, an unconfigured mailbox
    logs every statement as delivered.
    """
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "wilkem.ventures@gmail.com")
    user = getattr(settings, "EMAIL_HOST_USER", "")
    password = getattr(settings, "EMAIL_HOST_PASSWORD", "")

    if not user or not password:
        logger.warning(
            "Email skipped (EMAIL_HOST_USER/PASSWORD not set): to=%s subj=%s",
            to_email, subject,
        )
        return False

    try:
        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_content or "",
            from_email=from_email,
            to=[to_email],
        )
        msg.attach_alternative(html_content, "text/html")
        for filename, content, mimetype in attachments or []:
            msg.attach(filename, content, mimetype)
        msg.send(fail_silently=False)
        logger.info("Email sent to %s", to_email)
        return True
    except Exception as exc:
        logger.error("Email failed to %s: %s", to_email, exc)
        raise


# ---------------------------------------------------------------------------
# Message builders
# ---------------------------------------------------------------------------

def payment_sms_message(
    tenant_name: str, amount, unit_label: str, reference: str, statement: dict | None = None
) -> str:
    """Payment-received SMS. When a statement is supplied, the five named
    totals (deposit, arrears b/f, month rent, other charges, unpaid balance)
    are appended so the SMS receipt carries the same figures as the email."""
    msg = (
        f"Dear {tenant_name}, payment of KES {amount:,.2f} received "
        f"for Unit {unit_label}. Ref: {reference}."
    )
    if statement:
        msg += (
            f" Statement (KES): Deposit {statement['security_deposit']}, "
            f"Arrears B/F {statement['arrears_bf']}, "
            f"Month Rent {statement['month_rent']}, "
            f"Other Charges {statement['other_charges']}, "
            f"Rent + Arrears {statement['rent_plus_arrears']}, "
            f"Unpaid Balance {statement['unpaid_balance']}."
        )
    return msg + " Thank you - Wilkem Edge."


def _row(label: str, value: str, *, bold: bool = False) -> str:
    weight = "font-weight:bold;" if bold else ""
    return (
        f'<tr><td style="padding:5px 8px;border:1px solid #c9c9c9;{weight}">{label}</td>'
        f'<td style="padding:5px 8px;border:1px solid #c9c9c9;text-align:right;{weight}">{value}</td></tr>'
    )


def _coded_row(label: str, value: str, coa_code: str, *, bold: bool = False) -> str:
    """Statement summary row carrying the GL code it reconciles to."""
    weight = "font-weight:bold;" if bold else ""
    return (
        f'<tr><td style="padding:5px 8px;border:1px solid #c9c9c9;{weight}">{_e(label)}</td>'
        f'<td style="padding:5px 8px;border:1px solid #c9c9c9;text-align:center;color:#555;font-size:9px;{weight}">{_e(coa_code)}</td>'
        f'<td style="padding:5px 8px;border:1px solid #c9c9c9;text-align:right;{weight}">{_e(value)}</td></tr>'
    )


def _ledger_row(row: dict) -> str:
    extra_lines = "".join(
        f'<div style="font-size:10px;color:#444">{_e(line)}</div>'
        for line in row["description_lines"][1:]
    )
    first_line = _e(row["description_lines"][0])
    neg = "color:#c20000;" if row.get("balance_negative") else ""
    return (
        f'<tr>'
        f'<td style="border:1px solid #cdcdcd;padding:3px 5px;text-align:center;font-size:10px">{row["index"]}</td>'
        f'<td style="border:1px solid #cdcdcd;padding:3px 5px;font-size:10px">{row["posting_date"]}</td>'
        f'<td style="border:1px solid #cdcdcd;padding:3px 5px;font-size:10px">{first_line}{extra_lines}</td>'
        f'<td style="border:1px solid #cdcdcd;padding:3px 5px;text-align:right;font-size:10px">{row["invoice_amount"]}</td>'
        f'<td style="border:1px solid #cdcdcd;padding:3px 5px;text-align:right;font-size:10px">{row["payment"]}</td>'
        f'<td style="border:1px solid #cdcdcd;padding:3px 5px;text-align:right;font-weight:bold;font-size:10px;{neg}">{row["balance"]}</td>'
        f'</tr>'
    )


def statement_email_html(
    tenant_name: str, statement: dict, *, amount=None, reference: str = ""
) -> str:
    """
    Full HTML rent statement that mirrors the PDF layout exactly:
    branded header, customer block + TOTAL BALANCE DUE, Statement Summary +
    Payment options, note, and the running-balance ledger.

    ``amount`` is the payment that prompted the statement, when there is one.
    A monthly statement run has no payment behind it, so it passes None and the
    closing note asks for settlement rather than thanking the tenant for money
    they have not sent.
    """
    # ── Statement Summary ──
    summary_rows = [
        _row("Arrears / Others", statement["arrears_others"]),
        _row("Current Month", statement["current_month_rent"]),
    ]
    if statement.get("is_business"):
        summary_rows.append(_row("16% VAT on Rent", statement["vat_on_rent"]))
    # Mirrors the PDF: without this line the summary silently netted the
    # tenant's payment into "Arrears / Others" and drove it negative.
    if statement.get("payments_received_value"):
        summary_rows.append(
            _row("Less: Payments Received", f"({statement['payments_received']})")
        )
    summary_rows.append(_row("Total KES Due:", statement["total_due"], bold=True))

    # ── Receipt breakdown — each line itemised with its COA code ──
    breakdown_rows = [
        _coded_row(label, amount, code, bold=(label == "Unpaid Balance"))
        for label, amount, code, _name in statement.get("breakdown_lines", [])
    ]

    # ── Payment options ──
    pay_rows = []
    if statement.get("has_bank"):
        bank = _e(statement["bank_name"])
        if statement.get("bank_branch"):
            bank += f", {_e(statement['bank_branch'])}"
        pay_rows.append(f'<tr><td style="padding:3px 6px;font-style:italic;color:#333;width:120px">Bank &amp; Branch:</td><td style="padding:3px 6px;font-weight:bold">{bank}</td></tr>')
        pay_rows.append(f'<tr><td style="padding:3px 6px;font-style:italic;color:#333">Account Number:</td><td style="padding:3px 6px;font-weight:bold">{_e(statement["bank_account"])}</td></tr>')
        if statement.get("bank_account_name"):
            pay_rows.append(f'<tr><td style="padding:3px 6px;font-style:italic;color:#333">Account Name:</td><td style="padding:3px 6px;font-weight:bold">{_e(statement["bank_account_name"])}</td></tr>')
    if statement.get("has_paybill"):
        pb = _e(statement["paybill_number"])
        acct = _e(statement.get("paybill_account") or "")
        acct_html = f" Account: <b>{acct}</b>" if acct else ""
        pay_rows.append(f'<tr><td colspan="2" style="padding:3px 6px">Or through Paybill No. <b>{pb}</b>{acct_html} ;</td></tr>')
    if not pay_rows:
        pay_rows.append('<tr><td colspan="2" style="padding:3px 6px">Please contact the management office for payment details.</td></tr>')

    # ── Customer block ──
    customer_lines = [f'<div style="font-weight:bold;font-size:12px">{_e(tenant_name)}</div>']
    if statement.get("care_of"):
        customer_lines.append(f'<div>c/o {_e(statement["care_of"])}</div>')
    if statement.get("kra_pin"):
        customer_lines.append(f'<div>PIN: {_e(statement["kra_pin"])}</div>')
    if statement.get("id_number"):
        customer_lines.append(f'<div>ID Card: {_e(statement["id_number"])}</div>')
    if statement.get("tenant_phone"):
        customer_lines.append(f'<div>Tel: {_e(statement["tenant_phone"])}</div>')
    customer_html = "".join(customer_lines)

    # ── Closing note ──
    # A payment-triggered receipt thanks the tenant for what they just sent; a
    # monthly statement has no payment behind it and asks for settlement.
    if amount is not None:
        ref_html = f" (Ref: <b>{_e(reference)}</b>)" if reference else ""
        closing_note = (
            f"Thank you for your payment of <b>KES {amount:,.2f}</b>{ref_html}. "
            "Your full rent statement above (also attached as a PDF) reflects "
            "the updated balance."
        )
    else:
        closing_note = (
            "Please find your rent statement above, also attached as a PDF. "
            f"The balance shown is <b>KES {_e(statement['total_due'])}</b>, "
            f"payable on or before {_e(statement['due_date'])}."
        )

    # ── Ledger ──
    ledger_rows_html = (
        "".join(_ledger_row(r) for r in statement["rows"])
        or '<tr><td colspan="6" style="border:1px solid #cdcdcd;padding:6px;text-align:center;font-size:10px">No transactions on record.</td></tr>'
    )

    return f"""\
<html><body style="font-family:Helvetica,Arial,sans-serif;color:#1a1a1a;padding:20px;font-size:10px;line-height:1.4">
<div style="max-width:760px;margin:0 auto">

  <!-- masthead -->
  <table style="border-collapse:collapse;width:100%">
    <tr>
      <td style="background:#e11d2e;color:#fff;text-align:center;padding:12px 8px;width:200px;vertical-align:middle">
        <div style="font-size:24px;font-weight:bold;letter-spacing:1px">WILKEM</div>
        <div style="font-size:10px;letter-spacing:4px">EDGE</div>
      </td>
      <td style="padding-left:14px;vertical-align:middle">
        <div style="font-size:14px;font-weight:bold">{_e(statement['entity_name'])}</div>
        {f'<div>{_e(statement["building_address"])}</div>' if statement.get('building_address') else ''}
        <div>{_e(statement['postal_address'])}</div>
        <div>Tel: {_e(statement['contact_phone'])}</div>
        <div style="color:#1d4ed8">Email: {_e(statement['contact_email'])}</div>
      </td>
    </tr>
  </table>

  <!-- title bar -->
  <table style="border-collapse:collapse;width:100%;border-top:1px solid #999;border-bottom:1px solid #999;margin-top:10px">
    <tr>
      <td style="padding:6px 0;color:#1d4ed8;font-weight:bold;font-size:12px">CUSTOMER RENT STATEMENT AS AT</td>
      <td style="padding:6px 0;text-align:right;color:#1d4ed8;font-weight:bold;font-size:12px">{_e(statement['statement_date'])}</td>
    </tr>
  </table>

  <!-- customer + balance -->
  <table style="border-collapse:collapse;width:100%;margin-top:6px">
    <tr>
      <td style="border:1px solid #b8b8b8;padding:8px 10px;width:55%;vertical-align:top">{customer_html}</td>
      <td style="border:1px solid #b8b8b8;padding:8px 10px;width:45%;vertical-align:top;font-weight:bold;font-size:11px">{_e(statement['unit_descriptor'])}</td>
    </tr>
    <tr>
      <td style="border:1px solid #b8b8b8;padding:6px 10px;text-align:right;font-weight:bold">TOTAL BALANCE DUE</td>
      <td style="border:1px solid #b8b8b8;padding:6px 10px;text-align:right;font-weight:bold;font-size:14px">Ksh{statement['total_due_whole']}</td>
    </tr>
  </table>

  <!-- summary + payment options -->
  <table style="border-collapse:collapse;width:100%;margin-top:8px">
    <tr>
      <td style="width:50%;padding-right:10px;vertical-align:top">
        <div style="font-weight:bold;margin-bottom:4px">Statement Summary</div>
        <table style="border-collapse:collapse;width:100%">{"".join(summary_rows)}</table>
      </td>
      <td style="width:50%;vertical-align:top">
        <div style="font-weight:bold;color:#1d4ed8;font-style:italic;margin-bottom:4px">Payment options</div>
        <table style="border-collapse:collapse;width:100%">{"".join(pay_rows)}</table>
      </td>
    </tr>
  </table>

  <!-- receipt breakdown — itemised with COA codes -->
  <div style="margin-top:10px">
    <div style="font-weight:bold;margin-bottom:4px">Receipt Breakdown</div>
    <table style="border-collapse:collapse;width:100%">
      <tr>
        <th style="padding:4px 8px;border:1px solid #c9c9c9;background:#f3d9c8;text-align:left;font-size:9px">Item</th>
        <th style="padding:4px 8px;border:1px solid #c9c9c9;background:#f3d9c8;text-align:center;font-size:9px">COA</th>
        <th style="padding:4px 8px;border:1px solid #c9c9c9;background:#f3d9c8;text-align:right;font-size:9px">KES</th>
      </tr>
      {"".join(breakdown_rows)}
    </table>
  </div>

  <!-- note -->
  <div style="border:1px solid #c9c9c9;padding:6px 8px;margin-top:8px;font-style:italic;color:#333">
    * Please note that ALL PAYMENTS should made to the Paybill / Bank account given in the Payment Options;
    The total amount payable is due on or before the {statement['due_day_ordinal']} day of the Billing Month.
  </div>

  <!-- ledger -->
  <table style="border-collapse:collapse;width:100%;margin-top:10px">
    <thead>
      <tr>
        <th style="background:#f3d9c8;border:1px solid #b8b8b8;padding:5px;font-size:10px;width:5%">#</th>
        <th style="background:#f3d9c8;border:1px solid #b8b8b8;padding:5px;font-size:10px;width:14%">Posting Date</th>
        <th style="background:#f3d9c8;border:1px solid #b8b8b8;padding:5px;font-size:10px;width:43%">Description</th>
        <th style="background:#f3d9c8;border:1px solid #b8b8b8;padding:5px;font-size:10px;width:12%">Invoice Amount</th>
        <th style="background:#f3d9c8;border:1px solid #b8b8b8;padding:5px;font-size:10px;width:12%">Payments</th>
        <th style="background:#f3d9c8;border:1px solid #b8b8b8;padding:5px;font-size:10px;width:14%">Balance</th>
      </tr>
    </thead>
    <tbody>{ledger_rows_html}</tbody>
  </table>

  <p style="margin-top:14px;color:#475569;font-size:11px">
    Dear {_e(tenant_name)},<br>
    {closing_note}
    If you notice any discrepancy, please contact the management office.
  </p>

</div>
</body></html>"""


def payment_statement_email_html(tenant_name: str, amount, reference: str, statement: dict) -> str:
    """Payment-receipt flavour of :func:`statement_email_html`."""
    return statement_email_html(tenant_name, statement, amount=amount, reference=reference)


def custom_email_html(subject: str, body: str) -> str:
    """Wrap a plain-text body as a simple branded HTML email."""
    paragraphs = "".join(
        f"<p style=\"margin:0 0 12px\">{_e(line)}</p>"
        for line in body.strip().split("\n\n")
        if line.strip()
    )
    return f"""
<html><body style="font-family:sans-serif;color:#1e293b;padding:24px;max-width:560px">
  <h2 style="color:#16a34a;margin:0 0 16px">{_e(subject)}</h2>
  {paragraphs}
  <hr style="border:none;border-top:1px solid #e2e8f0;margin:24px 0" />
  <p style="font-size:12px;color:#64748b;margin:0">Wilkem Edge</p>
</body></html>"""
