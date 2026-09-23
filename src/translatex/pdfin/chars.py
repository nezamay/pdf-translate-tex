"""Every character on a page, with the glyph corrections already applied.

This is the one place that turns a PDF's text layer into something the rest of the tool
can trust. Two things happen here that nothing downstream should have to repeat:

  * a font the width test convicted has its codes rewritten, so omega arrives as omega;
  * a glyph nobody could identify is marked unreadable rather than guessed at, and a
    fragment holding one is reproduced as a picture later instead of transcribed.

Marking is deliberately not the same as dropping. The character keeps its box and its
place in the line, because the crop that replaces it needs both.
"""

from __future__ import annotations

from dataclasses import dataclass

import pymupdf

from translatex.glyphs import decide_fonts
from translatex.glyphs.widths import FontVerdict
from translatex.pdfin.fonts import bare_name
from translatex.pdfin.fonts import family
from translatex.pdfin.fonts import style_from_name

# pymupdf's span flags; only the two we cannot get anywhere else.
_FLAG_ITALIC = 1 << 1
_FLAG_BOLD = 1 << 4


@dataclass(frozen=True)
class Char:
    """One drawn character, after the font's claims have been checked."""

    text: str
    bbox: tuple[float, float, float, float]
    page: int
    font: str
    size: float
    bold: bool = False
    italic: bool = False
    readable: bool = True

    @property
    def width(self) -> float:
        return self.bbox[2] - self.bbox[0]


def _style(span: dict) -> tuple[bool, bool]:
    """Bold and italic, from the descriptor when it speaks and the name when it does not."""
    flags = span.get("flags", 0)
    bold = bool(flags & _FLAG_BOLD)
    italic = bool(flags & _FLAG_ITALIC)
    if bold or italic:
        return bold, italic
    return style_from_name(span["font"])


def read_chars(
    doc: pymupdf.Document,
    verdicts: dict[str, FontVerdict] | None = None,
) -> list[Char]:
    """Every character in `doc`, corrected and marked, in the order the page draws it."""
    if verdicts is None:
        verdicts = decide_fonts(doc)

    out: list[Char] = []
    for page in doc:
        for block in page.get_text("rawdict")["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    name = bare_name(span["font"])
                    verdict = verdicts.get(name)
                    bold, italic = _style(span)
                    for ch in span["chars"]:
                        text = ch["c"]
                        readable = True
                        if verdict is not None:
                            # A convicted font decoded to the raw code in the first
                            # place — that is what being unreadable means here — so the
                            # code point of what pymupdf returned is the key to use.
                            code = ord(text)
                            text = verdict.overrides.get(code, text)
                            readable = code not in verdict.unexplained
                        out.append(
                            Char(
                                text=text,
                                bbox=tuple(ch["bbox"]),
                                page=page.number,
                                font=family(span["font"]),
                                size=span["size"],
                                bold=bold,
                                italic=italic,
                                readable=readable,
                            )
                        )
    return out


def unreadable_runs(chars: list[Char]) -> list[list[Char]]:
    """Maximal stretches of unreadable characters, each a candidate for one crop.

    Neighbouring unreadable glyphs are grouped because they are almost always one broken
    construction — a radical, a bracket pair, a stacked fraction — and cropping it whole
    keeps it looking like itself.
    """
    runs: list[list[Char]] = []
    current: list[Char] = []
    for char in chars:
        if char.readable:
            if current:
                runs.append(current)
                current = []
            continue
        if current and (current[-1].page != char.page or not _adjacent(current[-1], char)):
            runs.append(current)
            current = []
        current.append(char)
    if current:
        runs.append(current)
    return runs


def _adjacent(left: Char, right: Char) -> bool:
    """Whether two characters sit close enough to belong to one construction."""
    gap = right.bbox[0] - left.bbox[2]
    baseline_shift = abs(right.bbox[3] - left.bbox[3])
    return gap < max(left.size, right.size) and baseline_shift < max(left.size, right.size)
