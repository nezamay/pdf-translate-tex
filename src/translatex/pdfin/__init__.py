"""Reading a publisher's PDF: characters, boxes, typefaces."""

from translatex.pdfin.chars import Char
from translatex.pdfin.chars import Line
from translatex.pdfin.chars import read_chars
from translatex.pdfin.chars import read_lines
from translatex.pdfin.chars import stitch
from translatex.pdfin.chars import unreadable_runs
from translatex.pdfin.crops import Crop
from translatex.pdfin.crops import glyph_crops
from translatex.pdfin.crops import save_glyph
from translatex.pdfin.crops import tighten
from translatex.pdfin.crops import trim
from translatex.pdfin.crops import ink_box
from translatex.pdfin.fonts import bare_name
from translatex.pdfin.fonts import family
from translatex.pdfin.fonts import style_from_name
from translatex.pdfin.regions import columns
from translatex.pdfin.regions import figure_regions
from translatex.pdfin.words import Paragraph
from translatex.pdfin.words import Word
from translatex.pdfin.words import paragraphs
from translatex.pdfin.words import split_words

__all__ = [
    "Char",
    "Crop",
    "Line",
    "Paragraph",
    "Word",
    "bare_name",
    "columns",
    "family",
    "figure_regions",
    "glyph_crops",
    "ink_box",
    "paragraphs",
    "read_chars",
    "read_lines",
    "split_words",
    "stitch",
    "save_glyph",
    "style_from_name",
    "tighten",
    "trim",
    "unreadable_runs",
]
