"""Walk-the-building ordering for unit labels.

A roster filtered to one property reads naturally when it starts on the ground
floor and climbs: RB01…RB09, then RB101…RB111, then RB201… .

Sorting the label as text does not give that. ``MCF01`` (first floor) sorts
before ``MCG01`` (ground), and ``G-10`` sorts before ``G-2``. ``Unit.floor`` is
no help either — every unit in the roll still carries the field default of 0 —
so the floor has to be read off the label itself.
"""
import re

# Floor letters that appear in the Matasia commercial labels: MCG01 is ground,
# MCF01 is first. Only these two are recognised — a letter we have not seen in
# the coding sheet is treated as part of the building prefix, not as a floor.
FLOOR_LETTERS = {"G": 0, "F": 1}

_SEPARATORS = re.compile(r"[\s\-_/.]+")
_LEADING_LETTERS = re.compile(r"^([A-Z]+)(.*)$")
_LEADING_DIGITS = re.compile(r"^(\d+)(.*)$")


def unit_sort_key(label: str, building_code: str | None = None) -> tuple:
    """Sort key that puts a building's units in ground-floor-up, left-to-right order.

    ``building_code`` is the prefix the labels carry (``RB``, ``DON``, ``MC``…);
    passing it keeps the parser from mistaking a code letter for a floor letter.

        RB01  -> floor 0, unit 1        DON1A -> floor 1, unit A
        RB101 -> floor 1, unit 1        MCG01 -> floor 0, unit 1
        RB211 -> floor 2, unit 11       MCF01 -> floor 1, unit 1
    """
    text = _SEPARATORS.sub("", (label or "").strip().upper())
    rest = text

    # Drop the building prefix so what remains describes the floor and the unit.
    if building_code and rest.startswith(building_code.strip().upper()):
        rest = rest[len(building_code.strip().upper()):]
    else:
        letters = _LEADING_LETTERS.match(rest)
        if letters and letters.group(2):
            head, tail = letters.groups()
            # `MCG01` with no code on file: keep the trailing G/F, drop the `MC`.
            keep = 1 if head[-1] in FLOOR_LETTERS else 0
            rest = head[len(head) - keep:] + tail

    floor: int | None = None
    if rest and rest[0] in FLOOR_LETTERS:
        floor = FLOOR_LETTERS[rest[0]]
        rest = rest[1:]

    number = 0
    trailing = ""
    digits = _LEADING_DIGITS.match(rest)
    if digits:
        run, trailing = digits.groups()
        if floor is not None:
            number = int(run)
        elif len(run) >= 3:
            # Three digits or more encode the floor in everything but the last
            # two: 101 = floor 1 unit 01, 211 = floor 2 unit 11.
            floor, number = int(run[:-2]), int(run[-2:])
        elif len(run) == 2:
            # A two-digit scheme is a single floor: RB01–RB09, KH01–KH04.
            floor, number = 0, int(run)
        elif trailing:
            # DON1A / DON1B — the digit is the floor, the letter is the unit.
            floor, number = int(run), 0
        else:
            floor, number = 0, int(run)
    elif floor is None:
        floor = 0

    return (floor, number, trailing, text)
