"""
Built-in notification templates for Dr. Osoro.

Templates are hard-coded rather than stored in the DB — they are
starting points the admin can edit in the compose form before sending.
Placeholders like {tenant_name}, {unit_label}, {month}, {year},
{balance}, {amount}, {due_date} are resolved at compose time.
"""

TEMPLATES: list[dict] = [
    {
        "key": "rent_reminder",
        "label": "Rent Reminder",
        "description": "Friendly reminder that rent is due soon.",
        "channel": "sms",
        "subject": "Rent Reminder — {month}/{year}",
        "body": (
            "Hi {tenant_name}, this is a friendly reminder that rent for Unit {unit_label} "
            "(KES {amount}) is due on {due_date}. Kindly pay via M-Pesa Paybill. "
            "Thank you — Dr. Osoro Properties."
        ),
    },
    {
        "key": "rent_overdue",
        "label": "Overdue Notice",
        "description": "Firm notice for unpaid rent past the due date.",
        "channel": "both",
        "subject": "Overdue Rent — Unit {unit_label}",
        "body": (
            "Dear {tenant_name}, rent for Unit {unit_label} for {month}/{year} "
            "is now overdue. Outstanding balance: KES {balance}. "
            "Please settle immediately or contact the office. "
            "— Dr. Osoro Properties."
        ),
    },
    {
        "key": "payment_thanks",
        "label": "Payment Thank-You",
        "description": "Short thank-you after a payment clears.",
        "channel": "sms",
        "subject": "Payment Received",
        "body": (
            "Thank you {tenant_name}! We have received your payment of KES {amount} "
            "for Unit {unit_label}. — Dr. Osoro Properties."
        ),
    },
    {
        "key": "water_notice",
        "label": "Water / Utility Notice",
        "description": "Notify tenants about a water or utility interruption.",
        "channel": "sms",
        "subject": "Water Supply Notice",
        "body": (
            "Hi {tenant_name}, please note that water supply at your building will be "
            "interrupted on {due_date} for scheduled maintenance. We apologise for the "
            "inconvenience. — Dr. Osoro Properties."
        ),
    },
    {
        "key": "inspection",
        "label": "Inspection Notice",
        "description": "Give advance notice of a scheduled inspection.",
        "channel": "both",
        "subject": "Upcoming Inspection — Unit {unit_label}",
        "body": (
            "Dear {tenant_name}, we will be conducting an inspection of Unit {unit_label} "
            "on {due_date}. Kindly ensure access is available between 9 AM and 5 PM. "
            "— Dr. Osoro Properties."
        ),
    },
    {
        "key": "general_notice",
        "label": "General Announcement",
        "description": "Generic announcement for all tenants.",
        "channel": "sms",
        "subject": "Announcement",
        "body": (
            "Hi {tenant_name}, [write your message here]. "
            "— Dr. Osoro Properties."
        ),
    },
]


def get_template(key: str) -> dict | None:
    for t in TEMPLATES:
        if t["key"] == key:
            return t
    return None
