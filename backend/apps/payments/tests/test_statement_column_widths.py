"""
The ledger columns have to hold their worst-case text.

Spelling months in full made every date and every water line longer —
"Water usage September 2026 (12 Units @ KES 200)" no longer fitted the
Description column at its old width, and would have wrapped mid-phrase in the
PDF with nothing failing to say so.

xhtml2pdf lays out through reportlab, so reportlab's own metrics are what the
renderer will use. The widths are read out of the template rather than
duplicated here: a column narrowed in the HTML has to fail this test, which it
cannot do if the numbers are copied.
"""
import re
from pathlib import Path

import pytest
from reportlab.pdfbase.pdfmetrics import stringWidth

TEMPLATE = (
    Path(__file__).resolve().parents[1] / "templates" / "payments" / "statement_pdf.html"
)

BODY_FONT, BODY_SIZE = "Times-Roman", 10      # .ledger td
HEAD_FONT, HEAD_SIZE = "Times-Bold", 10       # .ledger th
PADDING = 10                                  # td padding: 4px 5px, both sides

# The longest thing each column ever has to print. September is the longest
# month name; the water line is the longest description the ledger builds.
WORST_CASE = {
    "#": ["18"],
    "Posting Date": ["30 September 2026"],
    "Description": [
        "Water usage September 2026 (12 Units @ KES 200)",
        "Balance brought forward - September-2026",
        "Three Months Rent Deposit",
    ],
    "Invoice Amount": ["1,234,567.89"],
    "Payments": ["1,234,567.89"],
    "Balance": ["1,234,567.89"],
}


def _header_widths() -> dict[str, int]:
    html = TEMPLATE.read_text(encoding="utf-8")
    found = dict(
        (label, int(px))
        for px, label in re.findall(
            r'<th style="width:\s*(\d+)px;">([^<]+)</th>', html
        )
    )
    assert found, "no ledger header widths found — has the template changed shape?"
    return found


def test_the_template_still_declares_every_column():
    assert set(_header_widths()) == set(WORST_CASE)


@pytest.mark.parametrize("column", sorted(WORST_CASE))
def test_the_worst_case_text_fits(column):
    width = _header_widths()[column]
    usable = width - PADDING
    widest = max(
        [stringWidth(s, BODY_FONT, BODY_SIZE) for s in WORST_CASE[column]]
        + [stringWidth(column, HEAD_FONT, HEAD_SIZE)]
    )
    assert widest <= usable, (
        f"{column!r} is {width}px ({usable}px usable) but needs {widest:.1f}pt — "
        f"the cell will wrap in the PDF"
    )


def test_the_columns_still_add_up_to_the_table_width():
    """A column widened without taking the room from another one silently
    stretches the table past the page box."""
    html = TEMPLATE.read_text(encoding="utf-8")
    declared = re.search(r'<table class="ledger" style="width:\s*(\d+)px;">', html)
    assert declared, "ledger table width not found"
    assert sum(_header_widths().values()) == int(declared.group(1))
