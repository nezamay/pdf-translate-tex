"""Reading a publisher's PDF: characters, boxes, typefaces."""

from translatex.pdfin.chars import Char
from translatex.pdfin.chars import Line
from translatex.pdfin.chars import read_chars
from translatex.pdfin.chars import read_lines
from translatex.pdfin.chars import unreadable_runs
from translatex.pdfin.fonts import bare_name
from translatex.pdfin.fonts import family
from translatex.pdfin.fonts import style_from_name
from translatex.pdfin.words import Paragraph
from translatex.pdfin.words import Word
from translatex.pdfin.words import paragraphs
from translatex.pdfin.words import split_words

__all__ = [
    "Char",
    "Line",
    "Paragraph",
    "Word",
    "bare_name",
    "family",
    "paragraphs",
    "read_chars",
    "read_lines",
    "split_words",
    "style_from_name",
    "unreadable_runs",
]
