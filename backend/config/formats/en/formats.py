"""Day-first date formats for Django's own forms and templates.

Reached through ``FORMAT_MODULE_PATH`` in ``config.settings.base``, which makes
Django prefer this over the stock ``en`` locale for every localized date.

Why it exists
-------------
The stock ``en`` locale is month-first. On the admin that was not merely
inconvenient, it was wrong in the quiet way: ``01/10/2026`` — 1 October to
everyone who uses this system — parsed clean as 10 January 2026 and was stored
without a murmur. A rejected date gets retyped; a date accepted as the wrong
month gets billed.

``DATE_INPUT_FORMATS`` therefore reads day-first, and ``DATE_FORMAT`` prints
the month by name so a date read back off a page cannot be re-entered wrongly.
Two-digit years are left out on purpose, matching the API and the dashboard:
``01/10/20`` is as likely to be an unfinished 2026 as it is to be 2020.
ISO stays at the head of the input list: it is unambiguous, it is what the
frontend's ``<input type="date">`` submits, and it is what every management
command writes.

The API has its own list — ``REST_FRAMEWORK["DATE_INPUT_FORMATS"]`` — because
DRF does not consult the locale. Keep the two in step.
"""

DATE_INPUT_FORMATS = [
    "%Y-%m-%d",  # 2026-10-01  (ISO — unambiguous, what the date picker sends)
    "%d/%m/%Y",  # 01/10/2026
    "%d-%m-%Y",  # 01-10-2026
    "%d.%m.%Y",  # 01.10.2026
    "%d %b %Y",  # 01 Oct 2026
    "%d %B %Y",  # 01 October 2026
]

DATETIME_INPUT_FORMATS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
    "%d-%m-%Y %H:%M:%S",
    "%d-%m-%Y %H:%M",
    "%d-%m-%Y",
]

# Printed, never parsed. The month is spelled so "01/10" can't be misread.
DATE_FORMAT = "d M Y"          # 01 Oct 2026
DATETIME_FORMAT = "d M Y H:i"  # 01 Oct 2026 14:30
SHORT_DATE_FORMAT = "d M Y"
