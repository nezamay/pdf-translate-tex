"""Reading a font's identity out of its name, because the descriptor will not say.

Journals typeset with Advent ship every cut of a face with Flags=32 and ItalicAngle=0 —
the italic bit is never set — and record the cut only in the font's name: "AdvOT907ecf5c.I"
is the italic, ".B" the bold, ".BI" both. Trusting the descriptor there flattens every
emphasis in the document, so headings and defined terms come out as body text.

The name also carries a subset prefix ("NEKDJE+") and sometimes a second "+NN" naming a
Unicode block, so the family has to be cut out of the middle.
"""

from __future__ import annotations

import re

_CUT_SUFFIX = re.compile(r"\.(BI|IB|B|I)$", re.IGNORECASE)

# "NEKBOB+AdvOT5bf56204.B+20" -> the trailing "+20" is a Unicode block, not a name part.
_BLOCK_SUFFIX = re.compile(r"\+[0-9a-f]{2}$", re.IGNORECASE)


def bare_name(name: str) -> str:
    """The font name without its six-letter subset prefix."""
    return str(name).split("+", 1)[-1] if name else ""


def family(name: str) -> str:
    """The face a name belongs to, with the subset, block and cut markers removed."""
    bare = _BLOCK_SUFFIX.sub("", bare_name(name))
    return _CUT_SUFFIX.sub("", bare)


def style_from_name(name: str) -> tuple[bool, bool]:
    """(bold, italic) as the name spells them, or (False, False) when it does not.

    Only meaningful for a descriptor that claims neither: a font that declares its own
    cut keeps what it declares, so this can never contradict a well-formed PDF.
    """
    match = _CUT_SUFFIX.search(_BLOCK_SUFFIX.sub("", bare_name(name)))
    if not match:
        return False, False
    suffix = match.group(1).upper()
    return "B" in suffix, "I" in suffix
