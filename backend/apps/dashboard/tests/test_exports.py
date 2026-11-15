"""What each download format is for, pinned.

CSV is a bare table to sort and import; Excel keeps the report's shape and
sums its own totals - but only when the sum is the figure on screen; PDF is
paged for reading. All three carry exactly the report's figures.
"""
import csv
import io
import re

from openpyxl import load_workbook

from apps.dashboard.exports import Column, Sheet, to_csv, to_pdf, to_xlsx


def _rent_roll():
    return Sheet(
        title="Rent roll",
        subtitle=["November 2026"],
        columns=[
            Column("unit", "Unit", width=8),
            Column("tenant", "Tenant", width=28),
            Column("billed", "Billed", "money", 12),
            Column("paid", "Paid (KES)", "money", 12),
        ],
        rows=[
            {"_style": "heading", "unit": "Matasia Commercial"},
            {"unit": "MCG05", "tenant": "Sidai Lonestar Healthcare", "billed": "123540", "paid": "123540"},
            {"unit": "MCG07", "tenant": "Ignite Access", "billed": "80736", "paid": "60000"},
            {"_style": "subtotal", "tenant": "Total Matasia Commercial", "billed": "204276", "paid": "183540"},
            {"_style": "heading", "unit": "Matasia Residential"},
            {"unit": "MR203", "tenant": "Grace Wanjiku", "billed": "18000", "paid": ""},
            {"_style": "subtotal", "tenant": "Total Matasia Residential", "billed": "18000", "paid": "0"},
            # Deliberately not the sum of the lines: a report total that means
            # something else must keep its own figure, never a SUM.
            {"_style": "total", "tenant": "Total", "billed": "222276", "paid": "999"},
        ],
        notes=["Balances include VAT."],
    )


def _csv_rows(sheet):
    return list(csv.reader(io.StringIO(to_csv(sheet).decode("utf-8-sig"))))


# ── CSV ──────────────────────────────────────────────────────────────────────

def test_csv_is_one_header_row_then_the_lines():
    rows = _csv_rows(_rent_roll())
    assert rows[0] == ["Section", "Unit", "Tenant", "Billed (KES)", "Paid (KES)"]
    assert rows[1:] == [
        ["Matasia Commercial", "MCG05", "Sidai Lonestar Healthcare", "123540.00", "123540.00"],
        ["Matasia Commercial", "MCG07", "Ignite Access", "80736.00", "60000.00"],
        ["Matasia Residential", "MR203", "Grace Wanjiku", "18000.00", ""],
    ]


def test_csv_without_sections_has_no_section_column():
    sheet = Sheet("Plain", [Column("a", "A"), Column("n", "N", "money")], [{"a": "x", "n": "1"}])
    assert _csv_rows(sheet) == [["A", "N (KES)"], ["x", "1.00"]]


def test_csv_section_label_can_be_named():
    sheet = _rent_roll()
    sheet.section_label = "Building"
    assert _csv_rows(sheet)[0][0] == "Building"


# ── Excel ────────────────────────────────────────────────────────────────────

def _book(sheet, data_only=False):
    return load_workbook(io.BytesIO(to_xlsx(sheet)), data_only=data_only).active


def _row_of(ws, text):
    for row in ws.iter_rows():
        if any(c.value == text for c in row):
            return row
    raise AssertionError(f"{text!r} not in sheet")


def test_xlsx_subtotals_are_sums_of_their_lines():
    ws = _book(_rent_roll())
    commercial = _row_of(ws, "Total Matasia Commercial")
    assert re.fullmatch(r"=SUM\(C\d+:C\d+\)", commercial[2].value)
    assert re.fullmatch(r"=SUM\(D\d+:D\d+\)", commercial[3].value)


def test_xlsx_total_sums_the_subtotals_only_when_that_is_the_figure():
    ws = _book(_rent_roll())
    total = _row_of(ws, "Total")
    assert re.fullmatch(r"=SUM\(C\d+,C\d+\)", total[2].value)  # 204276 + 18000
    assert total[3].value == 999  # not 183540 + 0: kept as the report's figure


def test_xlsx_formulas_carry_their_result_for_previews():
    ws = _book(_rent_roll(), data_only=True)
    assert _row_of(ws, "Total Matasia Commercial")[2].value == 204276
    assert _row_of(ws, "Total")[2].value == 222276


def test_xlsx_lines_fold_under_their_heading():
    ws = _book(_rent_roll())
    line = _row_of(ws, "Sidai Lonestar Healthcare")[0].row
    heading = _row_of(ws, "Matasia Commercial")[0].row
    subtotal = _row_of(ws, "Total Matasia Commercial")[0].row
    assert ws.row_dimensions[line].outline_level == 1
    assert ws.row_dimensions[heading].outline_level == 0
    assert ws.row_dimensions[subtotal].outline_level == 0


def test_xlsx_keeps_the_letterhead_title_and_notes():
    raw = to_xlsx(_rent_roll())
    assert b"xl/media/image1.png" in raw  # the Wilkem logo heads the sheet
    ws = load_workbook(io.BytesIO(raw)).active
    values = [c.value for row in ws.iter_rows() for c in row if c.value is not None]
    assert "Rent roll" in values and "November 2026" in values
    assert "Balances include VAT." in values
    assert "Billed (KES)" in values and "Paid (KES)" in values


# ── PDF ──────────────────────────────────────────────────────────────────────

def test_pdf_is_portrait_unless_the_columns_need_room():
    assert b"/MediaBox [ 0 0 595.2756 841.8898 ]" in to_pdf(_rent_roll())
    wide = _rent_roll()
    wide.columns = wide.columns + [Column(f"x{i}", f"X{i}", width=12) for i in range(4)]
    assert b"/MediaBox [ 0 0 841.8898 595.2756 ]" in to_pdf(wide)


def test_pdf_carries_the_logo():
    assert b"/Subtype /Image" in to_pdf(_rent_roll())


def test_pdf_pages_a_long_report():
    sheet = _rent_roll()
    sheet.rows = [{"unit": f"U{i}", "tenant": f"Tenant {i}", "billed": "1000", "paid": "1000"}
                  for i in range(200)]
    assert re.search(rb"/Count [2-9]", to_pdf(sheet))


def test_pdf_handles_an_empty_report():
    sheet = _rent_roll()
    sheet.rows = []
    assert to_pdf(sheet).startswith(b"%PDF")
    assert _csv_rows(sheet) == [["Unit", "Tenant", "Billed (KES)", "Paid (KES)"]]
