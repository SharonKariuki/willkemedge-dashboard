"""Turn any report table into a CSV, Excel or PDF download.

A report describes itself once as a :class:`Sheet` - title, the period and
filters it was run for, columns, rows and totals - and :func:`file_response`
writes that same sheet in whichever format was asked for. The figures in the
file are therefore exactly the figures on screen, in all three formats.

Rows are dicts keyed by column. A row may carry ``"_style"`` to set it apart:
``heading`` (an account or section title), ``opening`` / ``closing`` (a
ledger's carried balances), ``subtotal`` and ``total``.

Each format is shaped for what people do with it:

* **PDF** is for reading and filing: the company letterhead, the app's navy
  and teal, 8.5pt type, portrait unless the columns need landscape, and
  "Page x of y".
* **Excel** is for working the numbers: the same letterhead and styling,
  sections that collapse, a print layout, and subtotals and totals written as
  ``SUM`` formulas - but only where the formula gives exactly the figure on
  screen, with that figure stored as the cell's result so a phone or email
  preview that doesn't calculate still shows it.
* **CSV** is for sorting, filtering and importing: one header row and one row
  per line, nothing else. Section headings become a column, totals are left
  out (they would be summed twice), and the title and period are in the
  filename.
"""
from __future__ import annotations

import csv
import datetime as _dt
import io
import re
from dataclasses import dataclass, field
from decimal import Decimal

from django.http import HttpResponse
from django.utils import timezone

from apps.common.csv_safety import csv_safe

FORMATS = {
    "csv": ("text/csv; charset=utf-8", "csv"),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
    "pdf": ("application/pdf", "pdf"),
}

COMPANY = "Wilkem Ventures"

# The app's own palette (frontend/src/index.css), so a download looks like the
# screen it came from.
NAVY = "#0F2A43"
TEAL = "#0D9488"
INK = "#0F172A"
SLATE = "#334155"
MUTED = "#64748B"
RULE = "#CBD5E1"
HAIR = "#E2E8F0"
BAND = "#F1F5F9"

STRONG = ("heading", "closing", "subtotal", "total")
SUMMED = ("subtotal", "total")
CENT = Decimal("0.01")


@dataclass
class Column:
    key: str
    label: str
    #: text | money | date | number
    kind: str = "text"
    #: Relative width hint for PDF and Excel.
    width: int = 12


@dataclass
class Sheet:
    title: str
    columns: list[Column]
    rows: list[dict]
    #: Lines printed under the title: period, building, filters.
    subtitle: list[str] = field(default_factory=list)
    #: Short lines printed after the table (a basis note, a balance check).
    notes: list[str] = field(default_factory=list)
    #: CSV column that carries each ``heading`` row's text onto its lines.
    section_label: str = "Section"


def _logo_path() -> str:
    """The Wilkem logo the tenant statements carry (1200 x 448 px)."""
    from pathlib import Path

    import apps.payments

    return str(Path(apps.payments.__file__).parent / "static" / "payments" / "wilkem_logo.png")


LOGO_ASPECT = 1200 / 448


def _letterhead() -> dict:
    """The company details the tenant statements carry, so every document agrees."""
    from apps.payments import statement_service as s

    return {
        "name": s.DEFAULT_ENTITY_NAME,
        "postal": s.DEFAULT_POSTAL_ADDRESS,
        "phone": s.DEFAULT_CONTACT_PHONE,
        "email": s.DEFAULT_CONTACT_EMAIL,
    }


def _label(col: Column) -> str:
    """A money column says what it is counted in."""
    if col.kind == "money" and "KES" not in col.label.upper():
        return f"{col.label} (KES)"
    return col.label


def _plain(value, kind: str):
    """A cell's value as a CSV / Excel cell wants it."""
    if value is None or value == "":
        return ""
    if kind == "money":
        return Decimal(str(value)).quantize(CENT)
    if kind == "date" and isinstance(value, str):
        try:
            return _dt.date.fromisoformat(value)
        except ValueError:
            return value
    return value


def _printed(value, kind: str) -> str:
    """A cell as it reads on paper."""
    if value is None or value == "":
        return ""
    if kind == "money":
        amount = Decimal(str(value)).quantize(CENT)
        text = f"{abs(amount):,.2f}"
        return f"({text})" if amount < 0 else text
    if kind == "date":
        try:
            day = value if isinstance(value, _dt.date) else _dt.date.fromisoformat(str(value))
        except ValueError:
            return str(value)
        return day.strftime("%d %b %Y")
    return str(value)


def _stamp() -> str:
    return timezone.localtime().strftime("%d %b %Y %H:%M")


def _sectioned(sheet: Sheet) -> bool:
    return any(r.get("_style") == "heading" for r in sheet.rows)


def _section_text(row: dict, columns: list[Column]) -> str:
    """A heading row in one line: '1020 Bank Account · asset'."""
    parts = (_printed(row.get(c.key), c.kind) for c in columns if c.kind != "money")
    return " · ".join(p for p in parts if p)


# ── CSV ──────────────────────────────────────────────────────────────────────

def to_csv(sheet: Sheet) -> bytes:
    """One header row, then one row per line - a table Excel can sort and pivot."""
    out = io.StringIO()
    writer = csv.writer(out)
    sectioned = _sectioned(sheet)
    header = ([sheet.section_label] if sectioned else []) + [_label(c) for c in sheet.columns]
    writer.writerow([csv_safe(h) for h in header])

    section = ""
    for row in sheet.rows:
        style = row.get("_style", "")
        if style == "heading":
            section = _section_text(row, sheet.columns)
            continue
        if style in SUMMED:
            continue
        # Text cells go through csv_safe so a spreadsheet cannot execute them.
        # Money and dates are left alone: they are not text, and a negative
        # figure must stay a number.
        cells = [csv_safe(section)] if sectioned else []
        for c in sheet.columns:
            value = _plain(row.get(c.key), c.kind)
            if isinstance(value, _dt.date):
                value = value.isoformat()
            elif c.kind not in ("money", "number"):
                value = csv_safe(value)
            cells.append(value)
        writer.writerow(cells)
    # BOM so Excel opens the UTF-8 (KES, em dashes, names) correctly.
    return ("﻿" + out.getvalue()).encode("utf-8")


# ── Excel ────────────────────────────────────────────────────────────────────

def _ranges(col_letter: str, excel_rows: list[int]) -> list[str]:
    """[8, 9, 10, 14] -> ['D8:D10', 'D14']."""
    out, start, prev = [], None, None
    for n in excel_rows:
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            out.append(f"{col_letter}{start}:{col_letter}{prev}" if prev != start else f"{col_letter}{start}")
            start = prev = n
    if start is not None:
        out.append(f"{col_letter}{start}:{col_letter}{prev}" if prev != start else f"{col_letter}{start}")
    return out


def to_xlsx(sheet: Sheet) -> bytes:
    import xlsxwriter
    from xlsxwriter.utility import xl_col_to_name

    head = _letterhead()
    out = io.BytesIO()
    # Never turn a typed string into a formula, link or number: a tenant name
    # or description of "=HYPERLINK(...)" must stay text. Every cell below is
    # written with an explicit type as well.
    wb = xlsxwriter.Workbook(out, {
        "in_memory": True,
        "strings_to_formulas": False,
        "strings_to_urls": False,
        "strings_to_numbers": False,
    })
    wb.set_properties({"title": sheet.title, "author": COMPANY, "company": head["name"]})
    ws = wb.add_worksheet(re.sub(r"[\[\]:*?/\\]", "", sheet.title)[:31] or "Report")

    cols = sheet.columns
    last = max(len(cols) - 1, 0)
    sectioned = _sectioned(sheet)
    base = {"font_name": "Calibri", "font_size": 10, "font_color": INK, "valign": "top"}
    formats: dict[tuple, object] = {}

    def fmt(**props):
        key = tuple(sorted(props.items()))
        if key not in formats:
            formats[key] = wb.add_format({**base, **props})
        return formats[key]

    def band(r, text, f):
        if last:
            ws.merge_range(r, 0, r, last, text, f)
        else:
            ws.write_string(r, 0, text, f)

    # Letterhead: the logo in the first row, the title beneath it.
    ws.set_row(0, 40)
    ws.insert_image(0, 0, _logo_path(), {
        "x_scale": 0.11, "y_scale": 0.11, "x_offset": 2, "y_offset": 4,
        "object_position": 3, "description": head["name"],
    })
    band(1, sheet.title, fmt(bold=True, font_size=16, font_color=NAVY))
    ws.set_row(1, 24)
    r = 2
    for line in sheet.subtitle:
        band(r, line, fmt(font_color=SLATE))
        r += 1
    band(r, f"Printed {_stamp()}", fmt(font_size=9, italic=True, font_color=MUTED))
    r += 2

    header_row = r
    for i, col in enumerate(cols):
        numeric = col.kind in ("money", "number")
        ws.write_string(r, i, _label(col), fmt(
            bold=True, font_color=NAVY, bg_color=BAND, bottom=2, bottom_color=NAVY,
            text_wrap=True, valign="vcenter", align="right" if numeric else "left",
        ))
    ws.set_row(r, 20)
    r += 1

    def cell_format(style: str, col: Column, i: int):
        props: dict = {}
        if col.kind == "money":
            props["num_format"] = '#,##0.00;(#,##0.00);"–"'
        elif col.kind == "date":
            props.update(num_format="dd mmm yyyy", align="left")
        elif col.kind == "number":
            props["align"] = "right"
        if style == "heading":
            props.update(bold=True, font_color=NAVY, bottom=1, bottom_color=RULE)
        elif style == "opening":
            props.update(italic=True, font_color=MUTED, bottom=1, bottom_color=HAIR)
        elif style in ("closing", "subtotal"):
            props.update(bold=True, top=1, top_color=SLATE)
        elif style == "total":
            props.update(bold=True, font_color=NAVY, bg_color=BAND, top=1, top_color=NAVY,
                         bottom=6, bottom_color=NAVY)
        else:
            props.update(bottom=1, bottom_color=HAIR)
        if sectioned and i == 0 and col.kind == "text" and style not in ("heading", "total"):
            props["indent"] = 1
        return fmt(**props)

    def write_value(row_i, i, value, f):
        if value == "" or value is None:
            ws.write_blank(row_i, i, None, f)
        elif isinstance(value, Decimal):
            ws.write_number(row_i, i, float(value), f)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            ws.write_number(row_i, i, value, f)
        elif isinstance(value, _dt.date):
            ws.write_datetime(row_i, i, _dt.datetime.combine(value, _dt.time()), f)
        else:
            ws.write_string(row_i, i, str(value), f)

    # Rows a subtotal or total could be the sum of, by sheet row index.
    block: list[int] = []        # plain lines since the last heading / subtotal / total
    since_plain: list[int] = []  # plain lines since the last total
    since_subs: list[int] = []   # subtotals since the last total
    values: dict[int, dict] = {}

    def summed(row: dict, candidates: list[int], i: int, col: Column, row_i: int, f) -> bool:
        """Write ``=SUM(...)`` if it reproduces the figure exactly; say whether it did."""
        target = _plain(row.get(col.key), col.kind)
        if not candidates or not isinstance(target, Decimal):
            return False
        total = sum((values[c].get(col.key) or Decimal("0") for c in candidates), Decimal("0"))
        if total.quantize(CENT) != target:
            return False
        letter = xl_col_to_name(i)
        formula = "=SUM(" + ",".join(_ranges(letter, [c + 1 for c in candidates])) + ")"
        if len(formula) > 8000:
            return False
        ws.write_formula(row_i, i, formula, f, float(target))
        return True

    def money_values(row):
        return {c.key: _plain(row.get(c.key), c.kind) or None for c in cols if c.kind == "money"}

    for row in sheet.rows:
        style = row.get("_style", "")
        if style == "total":
            candidates = since_subs or since_plain
        elif style == "subtotal":
            candidates = block
        else:
            candidates = []
        for i, col in enumerate(cols):
            f = cell_format(style, col, i)
            if col.kind == "money" and style in SUMMED and summed(row, candidates, i, col, r, f):
                continue
            write_value(r, i, _plain(row.get(col.key), col.kind), f)

        if style == "":
            values[r] = money_values(row)
            block.append(r)
            since_plain.append(r)
        elif style == "heading":
            block = []
        elif style == "subtotal":
            values[r] = money_values(row)
            since_subs.append(r)
            block = []
        elif style == "total":
            block, since_plain, since_subs = [], [], []
        # Lines and opening balances fold away under their heading; the
        # heading, subtotal and closing rows stay as the collapsed summary.
        if sectioned and style in ("", "opening"):
            ws.set_row(r, None, None, {"level": 1})
        r += 1

    if not sheet.rows:
        band(r, "Nothing to report for this period.", fmt(italic=True, font_color=MUTED))
        r += 1
    last_data_row = r - 1

    if sheet.notes:
        r += 1
        for note in sheet.notes:
            ws.write_string(r, 0, note, fmt(font_size=9, italic=True, font_color=MUTED))
            r += 1

    for i, col in enumerate(cols):
        ws.set_column(i, i, max(col.width, len(_label(col)) + 2))
    ws.freeze_panes(header_row + 1, 0)
    if sheet.rows:
        ws.autofilter(header_row, 0, last_data_row, last)
    ws.outline_settings(True, False, True, False)
    ws.hide_gridlines(2)

    # Print: A4, one page wide, the header row on every page.
    ws.set_paper(9)
    if len(cols) > 5:
        ws.set_landscape()
    ws.fit_to_pages(1, 0)
    ws.repeat_rows(header_row)
    ws.set_margins(left=0.5, right=0.5, top=0.75, bottom=0.75)
    # The letterhead is on the sheet itself; the footer names the report on
    # every printed page. "&" is Excel's header/footer code character.
    footer = f"{head['name']}  ·  {sheet.title}  ·  Printed {_stamp()}".replace("&", "&&")
    ws.set_footer(f"&L&8{footer}&R&8Page &P of &N")

    wb.close()
    return out.getvalue()


# ── PDF ──────────────────────────────────────────────────────────────────────

def _canvas_class(draw_chrome):
    """A ReportLab canvas that knows the page count, for "Page x of y"."""
    from reportlab.pdfgen.canvas import Canvas

    class NumberedCanvas(Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._pages = []

        def showPage(self):  # noqa: N802 - ReportLab's name
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._pages)
            for state in self._pages:
                self.__dict__.update(state)
                draw_chrome(self, self._pageNumber, total)
                super().showPage()
            super().save()

    return NumberedCanvas


def to_pdf(sheet: Sheet) -> bytes:
    """A4 PDF drawn with ReportLab's table layout.

    Not the HTML route the statements use: xhtml2pdf took over half a minute
    on a nine-month general ledger, past the server's request timeout, where
    ReportLab draws the same thousand-line table in a second or two.
    """
    from xml.sax.saxutils import escape

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle

    C = colors.HexColor
    head = _letterhead()
    cols = sheet.columns
    sectioned = _sectioned(sheet)

    # Portrait reads best; landscape only when the columns need the room.
    wide = len(cols) > 6 or sum(c.width for c in cols) > 105
    pagesize = landscape(A4) if wide else A4
    margin = 1.4 * cm
    usable = pagesize[0] - 2 * margin

    base = ParagraphStyle("cell", fontName="Helvetica", fontSize=8.5, leading=10.5, textColor=C(INK))
    bold = ParagraphStyle("cellb", parent=base, fontName="Helvetica-Bold")
    navy = ParagraphStyle("celln", parent=bold, textColor=C(NAVY))
    italic = ParagraphStyle("celli", parent=base, fontName="Helvetica-Oblique", textColor=C(MUTED))
    para_for = {"heading": navy, "total": navy, "closing": bold, "subtotal": bold, "opening": italic}
    head_style = ParagraphStyle("head", fontName="Helvetica-Bold", fontSize=7, leading=9, textColor=C(NAVY))
    head_right = ParagraphStyle("headr", parent=head_style, alignment=2)
    title_style = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=17, leading=21,
                                 textColor=C(NAVY), spaceAfter=3)
    sub_style = ParagraphStyle("sub", fontName="Helvetica", fontSize=9, leading=12, textColor=C(SLATE))
    note_style = ParagraphStyle("note", fontName="Helvetica-Oblique", fontSize=7.5, leading=10,
                                textColor=C(MUTED))

    total_width = sum(c.width for c in cols) or 1
    widths = [usable * c.width / total_width for c in cols]
    numeric = [c.kind in ("money", "number") for c in cols]
    # Long text wraps; short columns stay plain strings, which draw much faster.
    wraps = [not num and w > 3.2 * cm for num, w in zip(numeric, widths, strict=True)]

    data = [[Paragraph(escape(_label(c).upper()), head_right if num else head_style)
             for c, num in zip(cols, numeric, strict=True)]]
    commands = [
        ("LINEBELOW", (0, 0), (-1, 0), 1.2, C(NAVY)),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 8.5),
        ("TEXTCOLOR", (0, 1), (-1, -1), C(INK)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 1), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 3.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    for i, num in enumerate(numeric):
        if num:
            commands.append(("ALIGN", (i, 0), (i, -1), "RIGHT"))

    for r, row in enumerate(sheet.rows, start=1):
        style = row.get("_style", "")
        cells = []
        for i, col in enumerate(cols):
            text = _printed(row.get(col.key), col.kind)
            if not text and col.kind == "money" and style == "":
                text = "–"
                commands.append(("TEXTCOLOR", (i, r), (i, r), C(RULE)))
            if wraps[i] and text:
                cells.append(Paragraph(escape(text), para_for.get(style, base)))
            else:
                cells.append(text)
        data.append(cells)

        if style in STRONG:
            commands.append(("FONT", (0, r), (-1, r), "Helvetica-Bold", 8.5))
        if style == "heading":
            commands += [
                ("TEXTCOLOR", (0, r), (-1, r), C(NAVY)),
                ("TOPPADDING", (0, r), (-1, r), 9),
                ("LINEBELOW", (0, r), (-1, r), 0.6, C(RULE)),
            ]
        elif style == "opening":
            commands += [
                ("FONT", (0, r), (-1, r), "Helvetica-Oblique", 8.5),
                ("TEXTCOLOR", (0, r), (-1, r), C(MUTED)),
                ("LINEBELOW", (0, r), (-1, r), 0.4, C(HAIR)),
            ]
        elif style in ("closing", "subtotal"):
            commands.append(("LINEABOVE", (0, r), (-1, r), 0.6, C(SLATE)))
        elif style == "total":
            commands += [
                ("TEXTCOLOR", (0, r), (-1, r), C(NAVY)),
                ("BACKGROUND", (0, r), (-1, r), C(BAND)),
                ("LINEABOVE", (0, r), (-1, r), 0.9, C(NAVY)),
                # The accountant's double rule under a final total.
                ("LINEBELOW", (0, r), (-1, r), 0.6, C(NAVY), None, None, None, 2, 1.6),
            ]
        else:
            commands.append(("LINEBELOW", (0, r), (-1, r), 0.4, C(HAIR)))
        # Lines sit indented under their section heading.
        if sectioned and style in ("", "opening", "closing", "subtotal"):
            commands.append(("LEFTPADDING", (0, r), (0, r), 14))
    if not sheet.rows:
        data.append(["Nothing to report for this period."] + [""] * (len(cols) - 1))
        commands.append(("TEXTCOLOR", (0, 1), (-1, 1), C(MUTED)))

    table = LongTable(data, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle(commands))

    story = [Paragraph(escape(sheet.title), title_style)]
    story += [Paragraph(escape(line), sub_style) for line in sheet.subtitle]
    story += [Spacer(1, 12), table]
    if sheet.notes:
        story.append(Spacer(1, 10))
        story += [Paragraph(escape(n), note_style) for n in sheet.notes]

    printed = _stamp()
    width, height = pagesize
    top = height - margin

    def chrome(canvas, page, total):
        canvas.saveState()
        # Letterhead: the logo on the left, how to reach the company on the
        # right, a teal rule beneath.
        logo_h = 30
        canvas.drawImage(_logo_path(), margin, top - logo_h, width=logo_h * LOGO_ASPECT, height=logo_h,
                         mask="auto")
        canvas.setFont("Helvetica-Bold", 7.5)
        canvas.setFillColor(C(NAVY))
        canvas.drawRightString(width - margin, top - 6, head["name"])
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(C(MUTED))
        canvas.drawRightString(width - margin, top - 16, head["postal"])
        canvas.drawRightString(width - margin, top - 26, f"Tel {head['phone']}  ·  {head['email']}")
        canvas.setStrokeColor(C(TEAL))
        canvas.setLineWidth(1.4)
        canvas.line(margin, top - logo_h - 6, width - margin, top - logo_h - 6)
        # Footer
        canvas.setStrokeColor(C(RULE))
        canvas.setLineWidth(0.5)
        canvas.line(margin, 1.15 * cm, width - margin, 1.15 * cm)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(C(MUTED))
        canvas.drawString(margin, 0.75 * cm, f"{sheet.title}  ·  Printed {printed}")
        canvas.drawRightString(width - margin, 0.75 * cm, f"Page {page} of {total}")
        canvas.restoreState()

    out = io.BytesIO()
    # The page frame pads its content by 6pt; pulling the margins out by that
    # much lines the title and table up with the letterhead at ``margin``.
    pad = 6
    doc = SimpleDocTemplate(out, pagesize=pagesize, leftMargin=margin - pad, rightMargin=margin - pad,
                            topMargin=margin + 46, bottomMargin=1.7 * cm,
                            title=sheet.title, author=head["name"])
    doc.build(story, canvasmaker=_canvas_class(chrome))
    return out.getvalue()


RENDERERS = {"csv": to_csv, "xlsx": to_xlsx, "pdf": to_pdf}


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "report"


def file_response(sheet: Sheet, fmt: str, filename: str | None = None) -> HttpResponse:
    content_type, ext = FORMATS[fmt]
    body = RENDERERS[fmt](sheet)
    name = f"{slug(filename or sheet.title)}.{ext}"
    response = HttpResponse(body, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    response["Access-Control-Expose-Headers"] = "Content-Disposition"
    return response


def export_format(request) -> str | None:
    """``?export=csv|xlsx|pdf`` - ``format`` is DRF's own parameter."""
    from rest_framework.exceptions import ValidationError

    fmt = (request.query_params.get("export") or "").lower() or None
    if fmt and fmt not in FORMATS:
        raise ValidationError({"export": "Use csv, xlsx or pdf."})
    return fmt
