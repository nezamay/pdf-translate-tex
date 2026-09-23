"""Reading the subset fonts that lie about what they draw."""

from translatex.glyphs.readings import DECLARED
from translatex.glyphs.readings import GREEK
from translatex.glyphs.readings import greek_letter
from translatex.glyphs.readings import readings
from translatex.glyphs.widths import FontVerdict
from translatex.glyphs.widths import decide
from translatex.glyphs.widths import decide_fonts

__all__ = [
    "DECLARED",
    "GREEK",
    "FontVerdict",
    "decide",
    "decide_fonts",
    "greek_letter",
    "readings",
]
